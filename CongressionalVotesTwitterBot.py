import os
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import requests
import tweepy
import time
import re
import dotenv
import humanize

#enum for chamber
class Chamber(Enum):
    HOUSE = 'house'
    SENATE = 'senate'
    BOTH = 'both'

#enum for propublica endpoints
class Endpoints(Enum):
    VOTES = 'votes'
    MEMBERS = 'members'
    AMENDMENTS = 'amendments'

#globals
BASE_PATH = ''
BOT_SCREEN_NAME = 'congressvotesbt'
PROPUBLICA_BASE_URL = 'https://api.propublica.org/congress/v1/'
ENV_PATH = ''
TWITTER_CONSUMER_KEY = ''
TWITTER_CONSUMER_SECRET = ''
TWITTER_TOKEN = ''
TWITTER_TOKEN_SECRET = ''
PROPUBLICA_API_KEY = ''

#for testing
POST_TWEETS = True
UPDATE_BIO = False

def saveLastPostTimestamp(timestamp: datetime):
    #save the last post timestamp so we know which records (should) have already been posted
    log(f'Saving last post timestamp [{str(timestamp)}]')
    path = os.path.join(BASE_PATH, "Data")
    if not os.path.isdir(path):
        os.makedirs(path)

    path = os.path.join(path, "LastPostTimestamp.dat")
    with open(path, 'w+') as f:
        f.write(str(timestamp))

def getLastPostTimestamp():
    #grab the last post timestamp so we know which records (should) have already been posted
    path = os.path.join(BASE_PATH, "Data", "LastPostTimestamp.dat")

    if os.path.exists(path):
        with open(path, 'r') as f:
            date = f.read()
    else:
        #if no saved date, return current timestamp, move on from here
        date = datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S")

    date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
    log(f'Reading last post timestamp [{str(date)}]')
    return date

def getVotesInDateRange(startDate: datetime, endDate: datetime):
    #use api to return voting data in a date range
    votes = []
    endDate = endDate + timedelta(1)

    daysBetween = endDate - startDate
    daysBetween = daysBetween.days
    if daysBetween > 30:
        log(f'Date range[{str(startDate)} - {str(endDate)}] is larger than 30 days, splitting up...')
        thisDate = startDate

        while (thisDate < endDate):
            thisStart = thisDate
            thisDate += timedelta(30)
            if thisDate > endDate:
                thisDate = endDate
            
            log(f'Grabbing votes in date range[{str(thisStart)} - {str(thisDate)}]')
            url = PROPUBLICA_BASE_URL + Chamber.BOTH.value + "/" + Endpoints.VOTES.value + "/" + thisStart.strftime("%Y-%m-%d") + "/" + thisDate.strftime("%Y-%m-%d") + ".json"
            votes.extend(proPublicaAPIGet(url)['votes'])

    else:
        log(f'Grabbing votes in date range[{str(startDate)} - {str(endDate)}]')
        url = PROPUBLICA_BASE_URL + Chamber.BOTH.value + "/" + Endpoints.VOTES.value + "/" + startDate.strftime("%Y-%m-%d") + "/" + endDate.strftime("%Y-%m-%d") + ".json"
        votes = proPublicaAPIGet(url)['votes']

    return votes

def getRecentVotes():
    #use api to return recent votes
    log('Grabbing recent votes...')
    url = PROPUBLICA_BASE_URL + Chamber.BOTH.value + "/" + Endpoints.VOTES.value + "/recent.json"
    votes = proPublicaAPIGet(url)
    return votes

def proPublicaAPIGet(url):
    #send a get request to the propublica API
    headers = {'X-API-Key': PROPUBLICA_API_KEY}
    log(f"Sending ProPublica API GET Request [{url}]...")
    with requests.get(url, headers=headers) as r:
        log(f"API response with status code [{r.status_code}]...")
        if r.status_code == 200:
            return r.json()['results']
        else:
            return None

def getNewPostData(lastPost: datetime, votes):
    #takes a list of votes and the last post timestamp and returns votes after that timestamp
    log('Parsing out votes since last post...')
    newVotes = []
    for i in range(len(votes) - 1, -1, -1):
        date = datetime.strptime(votes[i]['date'] + " " + votes[i]['time'], "%Y-%m-%d %H:%M:%S")
        if date > lastPost:
            newVotes.append(votes[i])
    return newVotes

def getMemberData(memberID):
    #return data for a specific member
    log(f'Grabbing member data for member [{memberID}]')
    url = PROPUBLICA_BASE_URL + Endpoints.MEMBERS.value + "/" + memberID + ".json"
    member = proPublicaAPIGet(url)
    return member

def getAmendmentData(congress, number):
    #return data for a specific amendment
    log(f'Grabbing amendment data for amendment [{number}]')
    number = number.lower()
    number = number.replace(' ', '')
    number = number.replace('.', '')
    url = PROPUBLICA_BASE_URL + Endpoints.AMENDMENTS.value + "/" + congress + "/" + number + ".json"
    member = proPublicaAPIGet(url)
    return member

def getTwitterHandle(memberID):
    #return twitter handle for specific member
    log(f'Grabbing twitter handle for member [{memberID}]')
    sponsor_data = getMemberData(memberID)

    if sponsor_data != None:
        sponsor_data = sponsor_data[0]
        twitterHandle = sponsor_data['twitter_account']
    else:
        log(f"Error - No data returned from member API request...")
        twitterHandle = ''
    
    return twitterHandle

def postNewVotes(votes):
    #for each new vote, create the tweet and post it
    log('Posting new vote information...')

    for i in votes:
        congress = i['congress']
        session = i['session']
        chamber = i['chamber']
        roll_call = i['roll_call']

        log(f'Processing vote {chamber}-{congress}-{session}-{roll_call}...')
        
        #grab bill ID for bill information below
        if 'bill_id' in i['bill']:
            bill = i['bill']['number']
            description = i['bill']['title']
        else:
            bill = ''
            description = i['description']

        if description == None:
            description = ''

        #grab amendment information
        amendment = ''
        if 'amendment' in i:
            if 'number' in i['amendment']:
                amendment = i['amendment']['number']
                
        question = i['question']
        result = i['result']

        speakerVotes = ''
        voteText = ''
        if question == 'Election of the Speaker':
            for speaker in i['total']:
                votes = i['total'][speaker]
                if speakerVotes == '':
                    speakerVotes += f'{speaker} : {votes}'
                else:
                    speakerVotes += f'\n{speaker} : {votes}'
        else:
            yes_votes = i['total']['yes']
            no_votes = i['total']['no']
            not_voting = i['total']['not_voting']
            present = i['total']['present']

             #build vote string
            voteText = f'Y-{yes_votes}, N-{no_votes}'
            if present != 0:
                voteText += f', P-{present}'
            if not_voting != 0:
                voteText += f', NV-{not_voting}'

        #build bill string
        if bill != '':
            billText = f'Bill {bill.upper()}: '
        else:
            billText = ''

        #build tweet
        if voteText == '':
            #this should be a speaker vote
            tweet = f'{chamber} Vote {roll_call}\n{description}\n\n{question} {amendment}\n{result}'
        else:
            if amendment != '':
                tweet = f'{chamber} Vote {roll_call}\n{description}\n\n{question} {amendment}\n{result}: {voteText}'
                #check tweet length, make accomadations
                #may need to take question into account here too, but for now focusing on description
                if len(tweet) > 255:
                    tweet = f'{chamber} Vote {roll_call}\n{description[0:len(description) - (len(tweet) - 255)]}\n\n{question}\n{result}: {voteText}'
            else:
                tweet = f'{chamber} Vote {roll_call}\n{description}\n\n{question}\n{result}: {voteText}'

        #tweet initial vote tweet, save vote timestamp
        lastTweet = postTweet(tweet)
        if POST_TWEETS:
            saveLastPostTimestamp(datetime.strptime(i['date'] + " " + i['time'], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=1))

        if speakerVotes != '':
            tweet = f'@{BOT_SCREEN_NAME} Votes:\n{speakerVotes}'
            lastTweet = postTweet(tweet, lastTweet)

        #now post additional information to a reply of this tweet
        vote_url = i['url']
        if speakerVotes == '':
            democratVotes = "Dem: Y-" + str(i['democratic']['yes']) + ", N-" + str(i['democratic']['no']) + ", P-" + str(i['democratic']['present']) + ", NV-" + str(i['democratic']['not_voting'])
            republicanVotes = "Rep: Y-" + str(i['republican']['yes']) + ", N-" + str(i['republican']['no']) + ", P-" + str(i['republican']['present']) + ", NV-" + str(i['republican']['not_voting'])
            independentVotes = "Ind: Y-" + str(i['independent']['yes']) + ", N-" + str(i['independent']['no']) + ", P-" + str(i['independent']['present']) + ", NV-" + str(i['independent']['not_voting'])
            
            if independentVotes == "Ind: Y-0, N-0, P-0, NV-0":
                tweet = f'@{BOT_SCREEN_NAME} Vote Breakdown:\n{democratVotes}\n{republicanVotes}\n\nDetails:\n{vote_url}'
            else:
                tweet = f'@{BOT_SCREEN_NAME} Vote Breakdown:\n{democratVotes}\n{republicanVotes}\n{independentVotes}\n\nDetails:\n{vote_url}'
        else:
                tweet = f'@{BOT_SCREEN_NAME} Vote Details:\n{vote_url}'

        #tweet voting breakdown
        lastTweet = postTweet(tweet, lastTweet)

        #grab propublica vote link:
        propublicaVoteLink = getPropublicaVoteLink(chamber, congress, roll_call, session)

        #grab c span vote link
        date = datetime.strptime(i['date'] + " " + i['time'], "%Y-%m-%d %H:%M:%S")
        cspanLink = getCSpanClipLink(chamber, congress, roll_call, date)
        if cspanLink == None:
            cspanLink = ''

        #grab govtrack vote link
        govtrackVoteLink = getGovTrackVoteLink(congress, date, chamber, roll_call)

        tweet = f'@{BOT_SCREEN_NAME} Vote Links\n'
        if (cspanLink != ''):
            tweet = f'{tweet}C-SPAN Clip: {cspanLink}'
        tweet = f'{tweet}\nProPublica: {propublicaVoteLink}'
        tweet = f'{tweet}\nGovTrack: {govtrackVoteLink}'
        
        #tweet additional vote information
        lastTweet = postTweet(tweet, lastTweet, True)

        #grab nomination ID for nomination information below
        nomination = ''
        if 'nomination' in i:
            if 'number' in i['nomination']:
                nomination = i['nomination']['number']

                #now tweet nomination data if any
                nominationLink = getCongressNominationLink(congress, nomination)
                tweet = f'@{BOT_SCREEN_NAME} Nomination {nomination}\nDetails: {nominationLink}'
                lastTweet = postTweet(tweet, lastTweet, True)

        #now tweet amendment information if any
        if amendment != '':
            #get sponsor info
            sponsor = i['amendment']['sponsor']
            sponsor_id = i['amendment']['sponsor_id']
            sponsor_party = i['amendment']['sponsor_party']
            sponsor_state = i['amendment']['sponsor_state']
            twitterHandle = getTwitterHandle(sponsor_id)

            #build sponsor info
            sponsorText = ''
            if (sponsor_id != ''):
                if (twitterHandle != ''):
                    sponsorText = f'Amd Sponsor: .@{twitterHandle} {sponsor_party}, {sponsor_state}\n'
                else:
                    sponsorText = f'Amd Sponsor: {sponsor}, {sponsor_party}, {sponsor_state}\n'

            #amendment data doesn't seem to be returning from the api properly, so we'll leave this for now
            #info = getAmendmentData(congress, amendment)

            amendmentDescription = i['description']

            #tweet amendment information
            tweet = f'@{BOT_SCREEN_NAME} {sponsorText}Amd Details: {amendmentDescription}'
            if len(tweet) > 255:
                tweet = tweet[0:251] + '...'
            lastTweet = postTweet(tweet, lastTweet)

        #now post bill data if any
        if bill != '':
            bill_url = i['bill']['api_uri']

            govtrack_url = ''
            if bill_url != None:
                bill_data = proPublicaAPIGet(bill_url)
                bill_data = bill_data[0]
                bill_details_url = bill_data['congressdotgov_url']
                bill_sponsor = bill_data['sponsor_title'] + " " + bill_data['sponsor']
                bill_sponsor_id = bill_data['sponsor_id']
                govtrack_url = bill_data['govtrack_url']
                
                #if sponsored, get sponsor information
                twitterHandle = getTwitterHandle(bill_sponsor_id)
            
                #now build the tweet
                sponsorText = ''
                if (bill_sponsor_id != ''):
                    if (twitterHandle != ''):
                        sponsorText = f'Bill Sponsor: .@{twitterHandle}\n'
                    else:
                        sponsorText = f'Bill Sponsor: {bill_sponsor}\n'
            
                #tweet bill information
                tweet = f'@{BOT_SCREEN_NAME} {sponsorText}\nBill Details: {bill_details_url}'
                lastTweet = postTweet(tweet, lastTweet)
        
            #grab c span bill link
            bill_number = i['bill']['number']
            cpanBillLink = getCSpanBillLink(congress, bill_number)

            #grab propublica bill link
            propublicaBillLink = getPropublicaBillLink(congress, bill_number)

            #tweet additional bill links
            if govtrack_url == '':
                tweet = f'@{BOT_SCREEN_NAME} Bill Links\nC-SPAN: {cpanBillLink}\nProPublica: {propublicaBillLink}'
            else:
                tweet = f'@{BOT_SCREEN_NAME} Bill Links\nC-SPAN: {cpanBillLink}\nProPublica: {propublicaBillLink}\nGovTrack: {govtrack_url}'
            lastTweet = postTweet(tweet, lastTweet, True)
        
        log(f"Waiting for 300 seconds...")
        time.sleep(300)

def postTweet(tweet, replyToID=None, stopEmbeds=False):
    sleep_time = 60
    posted = False

    log(f"Waiting for 10 seconds...")
    time.sleep(10)

    #post a tweet, return tweet ID
    if replyToID != None:
        log(f"Posting tweet [{tweet}] in reply to tweet [{replyToID}]")
    else:
        log(f"Posting tweet [{tweet}]")

    if len(tweet) > 255:
        log(f"Warning: Tweet [{tweet}] is greater than 255 characters")
        #shortening tweet
        tweet = tweet.replace("On Motion to ", "")
        tweet = tweet.replace("Suspend the Rules and ", "")
        tweet = tweet[0:252]
        tweet += '...'
    
    while not posted:
        if POST_TWEETS:
            client = tweepy.Client(consumer_key=TWITTER_CONSUMER_KEY, consumer_secret=TWITTER_CONSUMER_SECRET, access_token=TWITTER_TOKEN, access_token_secret=TWITTER_TOKEN_SECRET)
            #if stopEmbeds:
            #    response = client.create_tweet(in_reply_to_tweet_id=replyToID, text=tweet)
            #else:
            #    response = client.create_tweet(in_reply_to_tweet_id=replyToID, text=tweet)
            try:
                response = client.create_tweet(in_reply_to_tweet_id=replyToID, text=tweet)
                posted = True
            except Exception as e:
                log(e)
                log(f"Waiting for {sleep_time} seconds...")
                time.sleep(sleep_time)
                sleep_time *= 2

    return response.data['id']

def getCSpanClipLink(chamber, congress, voteNumber, date):
    log(f"Grabbing C Span clip link for {congress}-{chamber}-{voteNumber}")

    #we build a search link
    searchLink = f'https://www.c-span.org/congress/votes/?congress={congress}&chamber={chamber}&vote-status-sort=all&vote-number-search={voteNumber}&vote-start-date={date.month}%2F{date.day}%2F{date.year}&vote-end-date={date.month}%2F{date.day}%2F{date.year}'

    #run a get to retrieve the search page
    with requests.get(searchLink) as searchData:
        #parse the video result from the html
        link = re.findall('''"\/\/www\.c-span\.org\/video\/\?.+"''', searchData.text)
        finalLink = ''
        if link != None and link != '' and len(link) > 0:
            link = link[0]
            link = link.replace('"', '')
            link = link.replace('//', '')
            link = link + "&vod"
            finalLink = link

        return finalLink

def getCSpanBillLink(congress, billNumber):

    billNumber = billNumber.replace(".", '')
    billNumber = billNumber.lower()
    link = f"https://www.c-span.org/congress/bills/bill/?{congress}/{billNumber}"
    return link

def getPropublicaBillLink(congress, billNumber):
    billNumber = billNumber.replace(".", '')
    billNumber = billNumber.lower()
    link = f"https://projects.propublica.org/represent/bills/{congress}/{billNumber}"
    return link

def getPropublicaVoteLink(chamber, congress, voteNumber, session):
    link = f'https://projects.propublica.org/represent/votes/{congress}/{chamber}/{session}/{voteNumber}'
    return link

def getGovTrackVoteLink(congress, date, chamber, voteNumber):
    if chamber.lower() == 'senate':
        chamberCode = 's'
    else:
        chamberCode = 'h'

    link = f'https://www.govtrack.us/congress/votes/{congress}-{date.year}/{chamberCode}{voteNumber}'
    return link

def getCongressNominationLink(congress, nomination):
    nomination = nomination.replace("PN", "")
    congress = humanize.ordinal(congress)
    link = f'https://www.congress.gov/nomination/{congress}-congress/{nomination}'
    return link

def updateLastUpdate():
    #fix later
    pass
#     #updates the bot bio with the last update time
#     t = Twitter(auth=OAuth(TWITTER_TOKEN, TWITTER_TOKEN_SECRET, TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET))
#     #auth = tweepy.OAuth1UserHandler(TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET, TWITTER_TOKEN, TWITTER_TOKEN_SECRET)
    
#     botProfile = t.users.show(screen_name = BOT_SCREEN_NAME)
#     botBio = botProfile['description']
#     botBioSplit = botBio.split("Last Update: ")
#     botBio = botBioSplit[0].strip() + ' ' + f'Last Update: {datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M:%S")} UTC'
    
#     log("Updating last update in Bio...")
#     t.account.update_profile(description = botBio)

def testPost():
    #just a sub to tweet the most recent vote for testing
    global POST_TWEETS

    POST_TWEETS = False
    startBot()

def log(message):
    #log a message, add timestamp to it
    message = f"{datetime.now()}: {message}"
    message = message.replace('\n', '\t')
    print(message)
    message += '\n'

    #save the last post timestamp so we know which records (should) have already been posted
    path = os.path.join(BASE_PATH, "Data", "Logs")
    if not os.path.isdir(path):
        os.makedirs(path)
    
    #write a new log each day
    fileName = f'Log_{datetime.strftime(datetime.today(), "%Y-%m-%d")}.txt'
    path = os.path.join(path, fileName)
    with open(path, 'a+') as f:
        f.write(message)
        
def startBot():
    #full process, run in a loop. Later will remove the loop and just schedule the program instead
    log(f"Bot starting up...")
    while 1 != 0:
        log(f"Starting update process...")
        lastDate = getLastPostTimestamp()
        voteData = getVotesInDateRange(lastDate, datetime.today())
        #voteData = getRecentVotes()
        if voteData != None:
            length = len(voteData)
            if (length > 0):
                log(f'{length} votes found since last post date...')
                newVoteData = getNewPostData(lastDate, voteData)
                log(f'{len(newVoteData)} new votes found since last post...')
                if(len(newVoteData) > 0):
                    postNewVotes(newVoteData)
        else:
            log(f"Error - No data returned from votes date range API request...")
        if UPDATE_BIO:
            updateLastUpdate()
        log(f"Update process complete")

        log(f"Waiting for 300 seconds...")
        time.sleep(300)

def main():
    global BASE_PATH 
    global TWITTER_CONSUMER_KEY 
    global TWITTER_CONSUMER_SECRET 
    global TWITTER_TOKEN 
    global TWITTER_TOKEN_SECRET 
    global PROPUBLICA_API_KEY 

    log('Initializing program...')

    #load constants
    BASE_PATH = Path(os.path.realpath(__file__)).parent

    #now load sensitive data, api keys from env file
    env_path = os.path.join(Path(os.path.dirname(os.path.realpath(__file__))).parent, "Keys", "CongressionalVotesTwitterBot.env")
    dotenv.load_dotenv(env_path)
    TWITTER_CONSUMER_KEY = os.getenv('TWITTER_CONSUMER_KEY')
    TWITTER_CONSUMER_SECRET = os.getenv('TWITTER_CONSUMER_SECRET')
    TWITTER_TOKEN = os.getenv('TWITTER_TOKEN')
    TWITTER_TOKEN_SECRET = os.getenv('TWITTER_TOKEN_SECRET')
    PROPUBLICA_API_KEY = os.getenv('PROPUBLICA_API_KEY')

    #run bot in test mode
    #testPost()

    #run the bot
    startBot()

if __name__ == '__main__':
    main()

