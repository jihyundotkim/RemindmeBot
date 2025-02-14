import asyncio
import re
import logging
import traceback

from enum import Enum
from datetime import datetime, timedelta
from dateutil import tz
from bson import ObjectId

import copy
from pytz import common_timezones as pytz_common_timezones, country_timezones

import discord
from discord.ext import commands, tasks

from lib.Connector import Connector
from lib.Reminder import Reminder, IntervalReminder
import lib.input_parser
import lib.ReminderRepeater
import util.interaction
from util.verboseErrors import VerboseErrors
from util.consts import Consts

from lib.Analytics import Analytics, Types

log = logging.getLogger('Remindme.Core')

class ReminderModule(commands.Cog):


    # =====================
    # internal functions
    # =====================


    def __init__(self, client):
        self.client: discord.AutoShardedBot = client

        log.debug('starting reminder event loops')

        if not self.check_pending_reminders.is_running():
            self.check_pending_reminders.start()
        if not self.check_pending_intervals.is_running():
            self.check_pending_intervals.start()
        if not self.check_reminder_cnt.is_running():
            self.check_reminder_cnt.start()
        if not self.check_interval_cnt.is_running():
            self.check_interval_cnt.start()
        if not self.clean_interval_orphans.is_running():
            self.clean_interval_orphans.start()

    def cog_unload(self):
        log.debug('stopping reminder event loops')
        self.check_pending_reminders.cancel()
        self.check_pending_intervals.cancel()
        self.check_reminder_cnt.cancel()
        self.check_interval_cnt.cancel()
        self.clean_interval_orphans.cancel()
        
        
    async def warn_author_dm(self, rem: Reminder, reason, channel:discord.TextChannel=None, err_msg=None):
        
        if rem.author == rem.target:
            # nothing be done here
            # dm already failed before, 
            # only convert reason from target->author
            if reason == Types.DeliverFailureReason.TARGET_FETCH:
                reason = Types.DeliverFailureReason.AUTHOR_FETCH
            elif reason == Types.DeliverFailureReason.TARGET_DM:
                reason = Types.DeliverFailureReason.AUTHOR_DM
            Analytics.reminder_not_delivered(rem, reason)
            return # no need for second try on same user
        

        # expose non-critical error of target not notified
        Analytics.reminder_not_delivered(rem, reason)


        # try to notify the author of the reminder
        try:
            author = await self.client.fetch_user(rem.author)
        except discord.errors.NotFound:
            # expose second counter for author warn failed
            log.warning(f'cannot find user {rem.author} for author warning')
            Analytics.reminder_not_delivered(rem, Types.DeliverFailureReason.AUTHOR_FETCH)
            return
        
        guild = self.client.get_guild(rem.g_id) if rem.g_id else None
        dm =  await author.create_dm()
        eb = rem.get_info_embed()

        guild_name = guild.name if guild else '*Unresolved Guild*'
        channel_name = channel.name if channel else '*Unresolved Channel*'
        
        help_text = 'Couldn\'t send the reminder into the requested channel\n\n'\
                   f'• Make sure I have permission to send messages into the channel `{channel_name}` on `{guild_name}`\n'\
                    '• or make sure the receiver allows to receive DMs from me\n'\
                    '• or edit the Reminder to be send into an existing channel'
        
        eb_warn = discord.Embed(title='Failed to deliver Reminder',
                                description=f'{help_text}',
                                color=Consts.col_crit)

        try:
            await dm.send(embed=eb_warn)
            await dm.send(embed=eb)
        except discord.errors.Forbidden:
            # dm has no embed permissions, embeds must always succeed
            log.warning(f'failed to send author warning')
            # expose second counter for author warn failed
            Analytics.reminder_not_delivered(rem, Types.DeliverFailureReason.AUTHOR_DM)
            return


    async def print_reminder_dm(self, rem: Reminder, channel=None, err_msg=None):
        # fallback to dm
        # target must be resolved, otherwise dm cannot be created

        try:
            target = await self.client.fetch_user(rem.target)
        except discord.errors.NotFound:
            log.warning(f'cannot find user {rem.target} for reminder DM')
            await self.warn_author_dm(rem, Types.DeliverFailureReason.TARGET_FETCH, channel=channel, err_msg=err_msg)
            return

        if target.bot:
            await self.warn_author_dm(rem, Types.DeliverFailureReason.TARGET_IS_BOT, channel=channel, err_msg=err_msg)
            return

        # dm if channel not existing anymor
        dm = await target.create_dm()
        
        
        # respect user preferences
        rem_type = Connector.get_reminder_type(rem.target)
        
        if rem_type == Connector.ReminderType.TEXT_ONLY:
            # text is identical to missing permission fallback
            # but the spoiler asking for more permissions is missing
            eb = None
            text = await rem.get_string(client=self.client, is_dm=True)
        elif rem_type == Connector.ReminderType.EMBED_ONLY:
            eb = await rem.get_embed(self.client, is_dm=True)
            text = ''
        else:
            eb = await rem.get_embed(self.client, is_dm=True)
            text = rem.get_embed_text(is_dm=True)
        
        view = util.interaction.UndeliveredView(reminder_id=rem._id, timeout=300)

        # first fallback is string-only message
        # second fallback is dm to user
        # DM never requires user mention (DM itself is a ping)
        try:
            await dm.send(text, embed=eb, view=view)
            if err_msg:
                await dm.send(f'||{err_msg}||')
        except discord.errors.Forbidden:
            # embeds can't be forbidden in DMs
            log.warning(f'failed to send reminder as DM to {rem.target}')
            await self.warn_author_dm(rem, Types.DeliverFailureReason.TARGET_DM, channel=channel, err_msg=err_msg)
            return


    async def print_reminder(self, rem: Reminder):

        async def send_message(guild, channel, text, embed, rem_type: Connector.ReminderType):
            if VerboseErrors.can_embed(channel):
                try:
                    if rem_type != Connector.ReminderType.EMBED_ONLY and \
                        rem_type != Connector.ReminderType.HYBRID:
                        view = None
                    elif isinstance(rem, IntervalReminder):                        
                        view = util.interaction.SnoozeIntervalView(rem, timeout=500)
                    else:
                        view = util.interaction.SnoozeView(rem, timeout=500)


                    tmp_msg = await channel.send(text, embed=embed, 
                                    allowed_mentions=discord.AllowedMentions.all(),
                                    view=view)

                    if view:
                        # for timeout functionality
                        view.message = tmp_msg
                                    
                    return True
                except discord.errors.Forbidden:
                    if isinstance(channel, discord.Thread) and channel.locked:
                        return False # no error on locked threads
                    log.error('failed to send embed, even though permissions had been assured')

            elif VerboseErrors.can_send_messages(channel):
                try:
                    # get the reminder string
                    # ignoring the user preferences
                    fallback = await rem.get_string(client=self.client)
                    fallback += '\n||This reminder can be more beautiful with `Embed Links` permissions||'
                    await channel.send(fallback)
                    return True
                except discord.errors.Forbidden:
                    if isinstance(channel, discord.Thread) and channel.locked:
                        return False # no error on locked threads
                    log.error('failed to send text message, even though permissions had been assured')

            return False

    
        # reminder is a DM reminder
        if not rem.g_id:
            await self.print_reminder_dm(rem)
            return

        guild = self.client.get_guild(rem.g_id)
        channel = guild.get_channel_or_thread(rem.ch_id) if guild else None

        if not channel:
            # this gets archived threads
            try:
                channel = await self.client.fetch_channel(rem.ch_id)
            except (discord.errors.NotFound, discord.errors.Forbidden):
                channel = None


        # no need to resolve author, target is sufficient
        guild_name = guild.name if guild else 'Unresolved Guild'
        if not channel:
            err = f'`You are receiving this dm, as the desired channel on \'{guild_name}\' is not existing anymore.`'
        elif isinstance(channel, discord.CategoryChannel):
            # cannot use category channels
            log.debug('tried to send reminder for category channel')
            err = f'`You are receivin this dm, as the desired channel \'{channel.name}\' on \'{guild_name}\' is not a Text- or Voice- channel`'
        else:
            err = None
        
        if err:
            log.debug('try to send reminder over dm')
            await self.print_reminder_dm(rem, channel=None, err_msg=err)
            return

        # respect guild preferences
        rem_type = Connector.get_reminder_type(guild.id)
        

        if rem_type == Connector.ReminderType.BAREBONE:
            eb = None
            text = await rem.get_string(client=self.client, barebone=True)
        elif rem_type == Connector.ReminderType.TEXT_ONLY:
            # text is identical to missing permission fallback
            # but the spoiler asking for more permissions is missing
            eb = None
            text = await rem.get_string(client=self.client, barebone=False)
        elif rem_type == Connector.ReminderType.EMBED_ONLY:
            eb = await rem.get_embed(self.client)
            text = rem.target_mention or f'<@{rem.target}>'
        else:
            eb = await rem.get_embed(self.client)
            text = rem.get_embed_text()

        success = await send_message(guild, channel, text, eb, rem_type)
        

        if not success:
            if isinstance(channel, discord.Thread) and channel.locked:
                err = f'`You are receiving this dm, as I the original thread \'{channel.name}\' on \'{guild.name}\' of this reminder was locked by a moderator.`'
            elif isinstance(channel, discord.Thread):
                err = f'`You are receiving this dm, as I do not have permission to send messages into the thread \'{channel.name}\' on \'{guild.name}\'.`'
            else:
                err = f'`You are receiving this dm, as I do not have permission to send messages into the channel \'{channel.name}\' on \'{guild.name}\'.`'

            await self.print_reminder_dm(rem, channel=channel, err_msg=err)

    # =====================
    # events functions
    # =====================



    @commands.Cog.listener()
    async def on_ready(self):
        log.info('loaded')


    @tasks.loop(hours=24)
    async def clean_interval_orphans(self):
        cnt = Connector.delete_orphaned_intervals()

        Analytics.reminder_deleted(Types.DeleteAction.ORPHAN, count=cnt)
        log.debug(f'deleted {cnt} orphaned interval(s)')


    @tasks.loop(seconds=45)
    async def check_pending_intervals(self):
        now = datetime.utcnow()
        
        pending_intvls = Connector.get_pending_intervals(now.timestamp())

        for interval in pending_intvls:
            # must be evaluated before new at is assigned
            Analytics.reminder_delay(interval, now=now, allowed_delay=2*60)
            
            interval.at = interval.next_trigger(now)
            Connector.update_interval_at(interval)
            
        for interval in pending_intvls:
            try:
                await self.print_reminder(interval)
            except Exception as e:
                log.error(f'interval not delivered, skipping. See exception below')
                t = (type(e), e, e.__traceback__)
                log.error(''.join(traceback.format_exception(*t)))
                Analytics.register_exception(e) # add these to ex counter

        self.last_loop = datetime.utcnow()
        sent_in = (self.last_loop-now).total_seconds()
        if sent_in > 1:
            log.debug(f'intervals sent in {sent_in}s')


    @tasks.loop(seconds=50)
    async def check_pending_reminders(self):
        now = datetime.utcnow()

        pending_rems = Connector.pop_elapsed_reminders(now.timestamp())
        
        for reminder in pending_rems:
            try:
                await self.print_reminder(reminder)
            except Exception as e:
                log.error(f'reminder not delivered, skipping. See exception below')
                t = (type(e), e, e.__traceback__)
                log.error(''.join(traceback.format_exception(*t)))
                Analytics.register_exception(e) # add these to ex counter

            Analytics.reminder_delay(reminder, now=now, allowed_delay=1*60)


        sent_in = (datetime.utcnow()-now).total_seconds()
        if sent_in > 1:
            log.debug(f'reminders sent in {sent_in}s')
        
    
   
    @tasks.loop(minutes=15)
    async def check_reminder_cnt(self):
        rems = Connector.get_reminder_cnt()
        Analytics.reminder_cnt(rems)

    @tasks.loop(minutes=15)
    async def check_interval_cnt(self):
        intvls = Connector.get_interval_cnt()
        Analytics.interval_cnt(intvls)
    

    @clean_interval_orphans.before_loop
    async def clean_interval_orphans_before(self):
        await self.client.wait_until_ready()

    @check_pending_intervals.before_loop
    async def check_pending_intervals_before(self):
        await self.client.wait_until_ready()

    @check_pending_reminders.before_loop
    async def check_pending_reminders_before(self):
        await self.client.wait_until_ready()

    @check_reminder_cnt.before_loop
    async def check_reminder_cnt_before(self):
        await self.client.wait_until_ready()

    @check_interval_cnt.before_loop
    async def check_interval_cnt_before(self):
        await self.client.wait_until_ready()

    # =====================
    # commands functions
    # =====================

def setup(client):
    client.add_cog(ReminderModule(client))
