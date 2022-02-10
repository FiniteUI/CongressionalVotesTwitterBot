import os
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import requests
from twitter import *
import time
import re
import dotenv

#enum for chamber
class Chamber(Enum):
    HOUSE = 'house'
    SENATE = 'senate'
    BOTH = 'both'

#enum for propublica endpoints
class Endpoints(Enum):
    VOTES = 'votes'
    MEMBERS = 'members'

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

def saveLastPostTimestamp(timestamp: datetime):
    #save the last post timestamp so we know which records (should) have already been posted
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
        #just returning project start date for now...
        date = '2022-02-07 20:29:31'

    date = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
    return date

def getVotesInDateRange(startDate: datetime, endDate: datetime):
    #use api to return voting data in a date range
    endDate = endDate + timedelta(1)
    url = PROPUBLICA_BASE_URL + Chamber.BOTH.value + "/" + Endpoints.VOTES.value + "/" + startDate.strftime("%Y-%m-%d") + "/" + endDate.strftime("%Y-%m-%d") + ".json"
    votes = proPublicaAPIGet(url)
    return votes

def getRecentVotes():
    #use api to return recent votes
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
    newVotes = []
    for i in range(len(votes) - 1, -1, -1):
        date = datetime.strptime(votes[i]['date'] + " " + votes[i]['time'], "%Y-%m-%d %H:%M:%S")
        if date > lastPost:
            newVotes.append(votes[i])
    return newVotes

def getMemberData(memberID):
    #return data for a specific member
    url = PROPUBLICA_BASE_URL + Endpoints.MEMBERS.value + "/" + memberID + ".json"
    member = proPublicaAPIGet(url)
    return member

def postNewVotes(votes):
    #for each new vote, create the tweet and post it
    with Twitter(auth=OAuth(TWITTER_TOKEN, TWITTER_TOKEN_SECRET, TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET)) as t:
        for i in votes:
            congress = i['congress']
            session = i['session']
            chamber = i['chamber']
            roll_call = i['roll_call']
            
            if 'bill_id' in i['bill']:
                bill = i['bill']['number']
            else:
                bill = ''

            if 'title' in i['bill']:
                description = i['bill']['title']
            else:
                description = i['description']

            if len(description) > 150:
                description = description[0:147] + "..."

            question = i['question']
            result = i['result']
            yes_votes = i['total']['yes']
            no_votes = i['total']['no']
            not_voting = i['total']['not_voting']
            present = i['total']['present']

            if bill != '':
                tweet = f'{chamber} Vote {roll_call}\nBill {bill.upper()}: {description}\n\n{question}\n{result}: Y-{yes_votes}, N-{no_votes}, P-{present}, NV-{not_voting}'
            else:
                tweet = f'{chamber} Vote {roll_call}\n{description}\n\n{result}: Y-{yes_votes}, N-{no_votes}, P-{present}, NV-{not_voting}'
            
            #tweet initial vote tweet, save vote timestamp
            log(f"Posting tweet [{tweet}]")
            t.statuses.update(status=tweet)
            saveLastPostTimestamp(datetime.strptime(i['date'] + " " + i['time'], "%Y-%m-%d %H:%M:%S") + timedelta(seconds=1))

            #now post additional information to a reply of this tweet
            democratVotes = "Dem: Y-" + str(i['democratic']['yes']) + ", N-" + str(i['democratic']['no']) + ", P-" + str(i['democratic']['present']) + ", NV-" + str(i['democratic']['not_voting'])
            republicanVotes = "Rep: Y-" + str(i['republican']['yes']) + ", N-" + str(i['republican']['no']) + ", P-" + str(i['republican']['present']) + ", NV-" + str(i['republican']['not_voting'])
            independentVotes = "Ind: Y-" + str(i['independent']['yes']) + ", N-" + str(i['independent']['no']) + ", P-" + str(i['independent']['present']) + ", NV-" + str(i['independent']['not_voting'])
            vote_url = i['url']
            
            if independentVotes == "Ind: Y-0, N-0, P-0, NV-0":
                tweet = f'@{BOT_SCREEN_NAME} Vote Breakdown:\n{democratVotes}\n{republicanVotes}\n\nDetails:\n{vote_url}'
            else:
                tweet = f'@{BOT_SCREEN_NAME} Vote Breakdown:\n{democratVotes}\n{republicanVotes}\n{independentVotes}\n\nDetails:\n{vote_url}'

            #tweet voting breakdown
            lastTweet = t.statuses.user_timeline(screen_name=BOT_SCREEN_NAME, count=1)[0]
            log(f"Posting tweet [{tweet}] in reply to tweet [{lastTweet['id']}]")
            t.statuses.update(in_reply_to_status_id=lastTweet['id'], status=tweet)

            #grab propublica vote link:
            propublicaVoteLink = getPropublicaVoteLink(chamber, congress, roll_call, session)

            #grab c span vote link
            date = datetime.strptime(i['date'] + " " + i['time'], "%Y-%m-%d %H:%M:%S")
            cspanLink = getCSpanClipLink(chamber, congress, roll_call, date)

            #grab govtrack vote link
            govtrackVoteLink = getGovTrackVoteLink(congress, date, chamber, roll_call)

            tweet = f'@{BOT_SCREEN_NAME} Vote Links\n'
            if (cspanLink != ''):
                tweet = f'{tweet}C-SPAN Clip: {cspanLink}'
            tweet = f'{tweet}\nProPublica: {propublicaVoteLink}'
            tweet = f'{tweet}\nGovTrack: {govtrackVoteLink}'
            
            #tweet additional vote information
            lastTweet = t.statuses.user_timeline(screen_name=BOT_SCREEN_NAME, count=1)[0]
            log(f"Posting tweet [{tweet}] in reply to tweet [{lastTweet['id']}]")
            t.statuses.update(in_reply_to_status_id=lastTweet['id'], status=tweet, card_uri='tombstone://card')

            #now post bill data if any
            if bill != '':
                bill_url = i['bill']['api_uri']
                bill_data = proPublicaAPIGet(bill_url)
                bill_data = bill_data[0]
                bill_details_url = bill_data['congressdotgov_url']
                bill_sponsor = bill_data['sponsor_title'] + " " + bill_data['sponsor']
                bill_sponsor_id = bill_data['sponsor_id']
                govtrack_url = bill_data['govtrack_url']
                
                #if sponsored, get sponsor information
                if(bill_sponsor_id != ''):
                    sponsor_data = getMemberData(bill_sponsor_id)

                    if sponsor_data != None:
                        sponsor_data = sponsor_data[0]
                        twitterHandle = sponsor_data['twitter_account']
                    else:
                        log(f"Error - No data returned from member API request...")
                        twitterHandle = ''
                else:
                    twitterHandle = ''
                
                #now build the tweet
                sponsorText = ''
                if (bill_sponsor_id != ''):
                    if (twitterHandle != ''):
                        sponsorText = f'Sponsor: .@{twitterHandle}\n'
                    else:
                        sponsorText = f'Sponsor: {bill_sponsor}\n'
                
                #tweet bill information
                tweet = f'@{BOT_SCREEN_NAME} {sponsorText}\nBill Details: {bill_details_url}'
                lastTweet = t.statuses.user_timeline(screen_name=BOT_SCREEN_NAME, count=1)[0]
                log(f"Posting tweet [{tweet}] in reply to tweet [{lastTweet['id']}]")
                t.statuses.update(in_reply_to_status_id=lastTweet['id'], status=tweet)
            
                #grab c span bill link
                bill_number = i['bill']['number']
                cpanBillLink = getCSpanBillLink(congress, bill_number)

                #grab propublica bill link
                propublicaBillLink = getPropublicaBillLink(congress, bill_number)

                #tweet additional bill links
                tweet = f'@{BOT_SCREEN_NAME} Bill Links\nC-SPAN: {cpanBillLink}\nProPublica: {propublicaBillLink}\nGovTrack: {govtrack_url}'
                lastTweet = t.statuses.user_timeline(screen_name=BOT_SCREEN_NAME, count=1)[0]
                log(f"Posting tweet [{tweet}] in reply to tweet [{lastTweet['id']}]")
                t.statuses.update(in_reply_to_status_id=lastTweet['id'], status=tweet, card_uri='tombstone://card')

def getCSpanClipLink(chamber, congress, voteNumber, date):
    #we build a search link
    searchLink = f'https://www.c-span.org/congress/votes/?congress={congress}&chamber={chamber}&vote-status-sort=all&vote-number-search={voteNumber}&vote-start-date={date.month}%2F{date.day}%2F{date.year}&vote-end-date={date.month}%2F{date.day}%2F{date.year}'

    #run a get to retrieve the search page
    with requests.get(searchLink) as searchData:
        #parse the video result from the html
        link = re.findall('''"\/\/www\.c-span\.org\/video\/\?.+"''', searchData.text)[0]
        link = link.replace('"', '')
        link = link.replace('//', '')
        link = link + "&vod"

        return link

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

def testPost():
    #just a sub to tweet the most recent vote for testing
    votes = getRecentVotes()
    if votes != None:
        votes = [votes['votes'][len(votes)]]
        postNewVotes(votes)
    else:
        log(f"Error - No data returned from recent votes API request...")

def log(message):
    #log a message, add timestamp to it
    print(f"{datetime.now()}: {message}")

def startBot():
    #full process, run in a loop. Later will remove the loop and just schedule the program instead
    log(f"Program starting...")
    while 1 != 0:
        log(f"Starting update process...")
        lastDate = getLastPostTimestamp()
        voteData = getVotesInDateRange(lastDate, datetime.today())
        #voteData = getRecentVotes()
        if voteData != None:
            length = len(voteData['votes'])
            if (length > 0):
                log(f'{length} votes found since last post date...')
                newVoteData = getNewPostData(lastDate, voteData['votes'])
                log(f'{len(newVoteData)} new votes found since last post...')
                if(len(newVoteData) > 0):
                    postNewVotes(newVoteData)
        else:
            log(f"Error - No data returned from votes date range API request...")
        log(f"Update process complete")
        time.sleep(300)

def main():
    global BASE_PATH 
    global TWITTER_CONSUMER_KEY 
    global TWITTER_CONSUMER_SECRET 
    global TWITTER_TOKEN 
    global TWITTER_TOKEN_SECRET 
    global PROPUBLICA_API_KEY 

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

    #run a test post
    #testPost()

    #run the bot
    startBot()

if __name__ == '__main__':
    main()

