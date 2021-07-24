# Remindme Bot

This is the Remindme Bot for discord.


Key features:
* remind yourself after a certain time period
* remind other users after a certain time period
* create complex repeating patterns (ics-rrules)

This bot is inspired by the reddit remindme bot and allows similar usage.

[Invite the Bot](https://discord.com/api/oauth2/authorize?client_id=831142367397412874&permissions=68608&scope=bot%20applications.commands) or view it's profile on [top.gg](https://top.gg/bot/831142367397412874)


## Some users cannot use the bot?

Make sure the user has the permission to perform `slash`-commands.
This is a recently introduced discord permission, and can control the access to bot commands.


## Create Repeating intervals

Create a "normal" interval with `/remindme` or `/remind` and set the `time` argument to be the first occurrence of your repeating event.
You can then press the `Set Interval` button to add repeating rules for the event.

The bot supports the full `rfc5545`-spec (the smallest interval is limited to daily) and allows the combination of up to 25 independent rules to define your custom repeating patterns.

## Commands

|Commands||
|---|---|
|```remindme <time> <message>```  | reminds you after the given `<time>` period| 
|```remind <user> <time> <message>``` | reminds another user after the given `<time>` period|
|```reminder_list``` | manage all your reminders for this server (interactive DM) |
|```timezone [set/get] <string>``` | set the timezone of your server, used for end-of-day calculation, defaults to UTC|


### Examples

```
/remindme 1y Hello future me
/remindme 2years This is a long time
/remindme 2 h drink some water
/remindme eow Buy groceries
/remindme 5 mi Whatever
/remindme 2 aug 3pm Is it hot outside?
/remindme 2021-09-02T12:25:00+02:00 iso is cool

/remind @User 1 mon What's up
/remind @User 24 dec Merry Christmas
/remind @User eoy Happy new year
```

## Time parsing

The time parser allows multiple formats for specifying the reminder period.

At the moment, different parameters cannot be combined.

```
	allowed absolutes are
		• eoy - remind at end of year
		• eom - remind at end of month
		• eow - remind at end of working week (Friday night)
		• eod - remind at end of day
	
	allowed intervals are
		• y(ears)
		• mo(nths)
		• w(eeks)
		• d(ays)
		• h(ours)
		• mi(ns)
	
	you can combine relative intervals like this
		1y 1mo 2 days -5h

	iso-timestamps are supported
		be aware that specifying a timezone will ignore the server timezone
	
	dates are supported, you can try different formats
		• 5 jul, 5th july, july 5
		• 23 sept at 3pm, 23 sept at 15:00
		• 2050

	tNote: the parser uses day-first and year-least
	      (01/02/21 -> 1st January)

	the reminder can occur as much as 1 minute delayed
```


### Note
The correct plural of the time interval does not matter
`/remindme 1 weeks Hey` is just as valid as `/remindme 2 week Ho`


### Github
https://github.com/Mayerch1/RemindmeBot
