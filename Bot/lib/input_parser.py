import re
import copy
from datetime import datetime, timedelta

import dateutil.parser
from dateutil.relativedelta import *
from dateutil import tz


def num_to_emoji(num: int):
    """convert a single digit to the numbers emoji
    Arguments:
        num {int}
    Returns:
        [str] -- unicode emoji, * if num was out of range [0..9]
    """
    if num == 1:
        return '1️⃣'
    elif num == 2:
        return '2️⃣'
    elif num == 3:
        return '3️⃣'
    elif num == 4:
        return '4️⃣'
    elif num == 5:
        return '5️⃣'
    elif num == 6:
        return '6️⃣'
    elif num == 7:
        return '7️⃣'
    elif num == 8:
        return '8️⃣'
    elif num == 9:
        return '9️⃣'
    elif num == 0:
        return '0️⃣'
    else:
        return '*️⃣'

def emoji_to_num(emoji):
    """convert unicode emoji back to integer
    Arguments:
        emoji {str} -- unicode to convert back, only supports single digits
    Returns:
        [int] -- number of emoji, None if emoji was not a number
    """
    if emoji == '1️⃣':
        return 1
    elif emoji == '2️⃣':
        return 2
    elif emoji == '3️⃣':
        return 3
    elif emoji == '4️⃣':
        return 4
    elif emoji == '5️⃣':
        return 5
    elif emoji == '6️⃣':
        return 6
    elif emoji == '7️⃣':
        return 7
    elif emoji == '8️⃣':
        return 8
    elif emoji == '9️⃣':
        return 9
    elif emoji == '0️⃣':
        return 0
    else:
        return None    


def _to_int(num_str: str, base: int=10):
        
    try:
        conv_int = int(num_str, base)
    except ValueError:
        conv_int = None
    finally:
        return conv_int


def _split_arg(arg):

    num_regex = re.search(r'-?\d+', arg)

    if num_regex:
        num_arg = num_regex.group()

        return (int(num_arg), arg.replace(num_arg, ''))
    else:
        return (None, arg)


def _join_spaced_args(args):

    joined_args = []
    
    i = 0
    while i < len(args):
        arg = args[i]

        if i+1 >= len(args):
            # cannot perform operation on last element
            joined_args.append(arg)

        # i+1 is guaranteed to exist
        elif (arg[0] != None and not arg[1]) and (not args[i+1][0] and args[i+1][1]):
            joined_args.append((arg[0], args[i+1][1]))
            i += 1 # skip next element

        else:
            # element is not complete, but following element doesn't allow joinup
            # this is caused by args like eom, eoy, ...
            joined_args.append(arg)
            
        i += 1

    return joined_args


def _parse_absolute(args, utcnow, now_local):
    """parse the date to absolute arguments
       (eoy, eom, ...)

       gives the absolute utc-date when the reminder
       should be triggered

    Args:
        args ([]]): list of arguments
        utcnow (datetime): current utc datetime (not tz-aware)
        now_local (datetime): local datetime (tz-aware)

    Returns:
        (datetime, str): non tz-aware date when reminder is trigger (in utc time), =utcnow on error
                         info string for parsing errors/warnings
    """

    total_intvl = timedelta(hours=0)
    error = ''
    info = ''

    for arg in args:
        if arg[1] == 'eoy':
            tmp = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            eoy = tmp + relativedelta(years=1, days=-1)
            total_intvl = eoy - now_local

        elif arg[1] == 'eom':
            tmp = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            eom = tmp + relativedelta(months=1, hours=-12)
            total_intvl = eom - now_local

        elif arg[1] == 'eow':
            w_day = now_local.weekday()
            week_start = now_local - timedelta(days=w_day)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

            eow = week_start + relativedelta(days=5, hours=-1)
            total_intvl = eow - now_local

        elif arg[1] == 'eod':
            tmp = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            eod = tmp + relativedelta(days=1, minutes=-15)
            total_intvl = eod - now_local

        else:
            info = info + f'• ignoring {arg}, as absolute and relative intervals cannot be mixed\n'


    return (utcnow + total_intvl, info)
            

def _parse_relative(args, utcnow):
    """parse the date to relative arguments
       (2y, 5d,...)

       gives the absolute utc-date when the reminder
       should be triggered

    Args:
        args ([]]): list of arguments
        utcnow (datetime): current utc datetime

    Returns:
        (datetime, str): non tz-aware date when reminder is trigger (in utc time), =utcnow on error
                         info string for parsing errors/warnings
    """

    total_intvl = timedelta(hours=0)
    info = ''

    for arg in args:

        intvl = timedelta(hours=0) # default in case of no-match

        if arg[0] == None:
            info = info + f'• Ignoring {arg}, as required numerical part is missing\n'
        else:
            if arg[1].startswith('y'):
                intvl = relativedelta(years=arg[0])

            elif arg[1].startswith('mo'):
                intvl = relativedelta(months=arg[0])

            elif arg[1].startswith('w'):
                intvl = relativedelta(weeks=arg[0])

            elif arg[1] == 'd' or arg[1].startswith('da'):
                # condition must not detect the month 'december'
                intvl = timedelta(days=arg[0]) 

            elif arg[1].startswith('h'):
                intvl = timedelta(hours=arg[0])

            elif arg[1].startswith('mi'):
                intvl = timedelta(minutes=arg[0])

            else:
                if arg[1] == 'm':
                    info = info + f'• Ambiguous reference to minutes/months. Please write out at least `mi` for minutes or `mo` for months\n'
                else:
                    info = info + f'• Ignoring {arg}, as this is not a known interval\n'
            
        total_intvl += intvl

    try:
        eval_interval = utcnow + total_intvl
    except Exception as e:
        return (utcnow, 'The interval is out of bounds/not a number')

    return (eval_interval, info)


def _parse_iso(input, utcnow, display_tz):

    try:
        remind_parse = dateutil.parser.isoparse(input)
    except ValueError as e:
        info = '• ' + ' '.join(e.args)
        remind_parse = None
    except:
        info = '• Unexpected parser error occurred'
        remind_parse = None
    else:
        info = ''

    # if the input string doesn't hold any timezone
    # it is converted into the local timzone
    # otherwise not modified
    # error assumes current utc time
    if remind_parse and not remind_parse.tzinfo:
        remind_aware = remind_parse.replace(tzinfo=display_tz)
    elif not remind_parse:
        remind_aware = utcnow.replace(tzinfo=tz.UTC)
    else:
        remind_aware = remind_parse


    # convert the parsed time back into a non-tz aware string
    # at utc
    remind_utc = remind_aware.astimezone(tz.UTC)
    remind_at = remind_utc.replace(tzinfo=None)

    return (remind_at, info)


def _parse_fuzzy(input, utcnow, display_tz):
    """parse a fuzzy input string using dateutil

       gives the absolute utc-date when the reminder
       should be triggered

    Args:
        input (str): input string, provided by user
        utcnow (datetime): current utc datetime
        display_tz (tzfile): the timezone of the guild/user

    Returns:
        (datetime, str): non tz-aware date when reminder is trigger (in utc time), =utcnow on error
                         info string for parsing errors/warnings
    """

    try:
        remind_parse = dateutil.parser.parse(input, fuzzy=True, dayfirst=True, yearfirst=False)
        remind_parse = remind_parse.replace(tzinfo=display_tz)
    except dateutil.parser.ParserError as e:
        info = '• ' + ' '.join(e.args)
        remind_parse = None
    except Exception as e:
        remind_parse = None
        info = '• Unexpected parser error occurred ({:s})'.format(''.join(e.args))
    else:
        info = ''

    # convert the given time from timezone to UTC
    # the resulting remind_at is not timezone aware
    if remind_parse:
        remind_utc = remind_parse.astimezone(tz.UTC)
        remind_at = remind_utc.replace(tzinfo=None)
    else:
        remind_at = utcnow

    return (remind_at, info)


def parse(input, utcnow, timezone='UTC'):
    """parse the input string into a datetime object
       this can be either relative or absolute, in relation to the input utcnow
       the function can respect the given timezone, for absolute and semi-absolute dates (e.g. oy)

    Args:
        input (str): input string, provided by the user
        utcnow (datetime): current utc time
        timezone (str, optional): target timezone (tzfile string). Defaults to 'UTC'.

    Raises:
        e: [description]

    Returns:
        (Datetime, str): Datetime: input target, returns utcnow on failure, might return dates in the past
                         str: info string on why the parser failed/ignored parts of the input
    """
    err = False

    display_tz = tz.gettz(timezone)
    tz_now = utcnow.replace(tzinfo=tz.UTC).astimezone(display_tz) # create local time, used for some parsers
    
    # first split into the different arguments
    # next separate number form char arguments

    rx = re.compile(r'[^a-zA-Z0-9-]') # allow negative sign
    args = rx.split(input)

    args = list(filter(lambda a: a != None and a != '', args))
    args = list(map(_split_arg, args))
    args = _join_spaced_args(args)
    

    remind_at, info = _parse_absolute(args, utcnow, tz_now)

    if remind_at == utcnow:
        remind_at, info = _parse_relative(args, utcnow)

    if remind_at == utcnow:
        remind_at, info = _parse_iso(input, utcnow, display_tz)

    # filter out queries which use 1m, as this is required to fail due to ambiguity with minutes/month
    if remind_at == utcnow and not re.match(r'-?\d+\W?m', input):
        remind_at, info = _parse_fuzzy(input, utcnow, display_tz)

    # negative intervals are not allowed
    if remind_at < utcnow:
        info += '• the given date must be in the future\n'
        info += '  current utc-time is:  {:s}\n'.format(utcnow.strftime('%Y-%m-%d %H:%M'))
        info += '  interpreted input is: {:s}\n'.format(remind_at.strftime('%Y-%m-%d %H:%M'))
        # return negative intervals, but keep warning

    return (remind_at, info)
