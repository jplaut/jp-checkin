from os import environ
import urllib
import urllib2
import ast
import simplejson as json
from collections import defaultdict

import pymongo
import redis
import pyres
import requests


APP_ID = environ.get('FACEBOOK_APP_ID')
APP_SECRET = environ.get('FACEBOOK_SECRET')

DBPATH=environ.get('MONGODBPATH')
DBNAME=environ.get('MONGODBDATABASE')
connection = pymongo.Connection(DBPATH)
db = connection[DBNAME]

redisHost = environ.get("REDIS_QUEUE_HOST")
redisPort = int(environ.get("REDIS_QUEUE_PORT"))
redisPassword = environ.get("REDIS_QUEUE_PASSWORD")

redisObject = redis.Redis(host=redisHost, port=redisPort, password=redisPassword)

redisQueue = pyres.ResQ(redisObject)


def oauth_login_url(preserve_path=True, next_url=None):
	fb_login_uri = ("https://www.facebook.com/dialog/oauth"
					"?client_id=%s&redirect_uri=%s" %
					(APP_ID, next_url))

	if environ.get('FBAPI_SCOPE'):
		fb_login_uri += "&scope=%s" % environ.get('FBAPI_SCOPE')
	return fb_login_uri
	
def get_facebook_callback_url(tokenNumber):
	return 'http://jp-checkin.herokuapp.com/?token_number=%s' % tokenNumber
	
def fql(fql, token, args=None):
	if not args:
		args = {}
	
	args["q"], args["format"], args["access_token"] = fql, "json", token
		
	return json.loads(
		urllib2.urlopen("https://graph.facebook.com/fql?" +
						urllib.urlencode(args)).read())
						
def fb_call(call, args=None):
	return json.loads(urllib2.urlopen("https://graph.facebook.com/" + call +
									  '?' + urllib.urlencode(args)).read())
									
def get_state_name(abrv):
	statesDict = {
	'AL':'Alabama', 
	'AK':'Alaska', 
	'AZ':'Arizona', 
	'AR':'Arkansas', 
	'CA':'California', 
	'CO':'Colorado', 
	'CT':'Connecticut', 
	'DC':'Washington DC',
	'DE':'Delaware', 
	'FL':'Florida', 
	'GA':'Georgia', 
	'HI':'Hawaii', 
	'ID':'Idaho', 
	'IL':'Illinois', 
	'IN':'Indiana', 
	'IA':'Iowa', 
	'KS':'Kansas', 
	'KY':'Kentucky', 
	'LA':'Louisiana', 
	'ME':'Maine', 
	'MD':'Maryland', 
	'MA':'Massachusetts', 
	'MI':'Michigan', 
	'MN':'Minnesota', 
	'MS':'Mississippi', 
	'MO':'Missouri', 
	'MT':'Montana', 
	'NE':'Nebraska', 
	'NV':'Nevada', 
	'NH':'New Hampshire', 
	'NJ':'New Jersey', 
	'NM':'New Mexico', 
	'NY':'New York', 
	'NC':'North Carolina', 
	'ND':'North Dakota', 
	'OH':'Ohio', 
	'OK':'Oklahoma', 
	'OR':'Oregon', 
	'PA':'Pennsylvania', 
	'RI':'Rhode Island', 
	'SC':'South Carolina', 
	'SD':'South Dakota', 
	'TN':'Tennessee', 
	'TX':'Texas', 
	'UT':'Utah', 
	'VT':'Vermont', 
	'VA':'Virginia', 
	'WA':'Washington', 
	'WV':'West Virginia', 
	'WI':'Wisconsin', 
	'WY':'Wyoming'
	}
	
	if abrv in statesDict:
		return statesDict[abrv]
	else:
		return None

class GetNewToken:
	queue = "*"
	
	@staticmethod
	def perform(tokenNumber):
		r = requests.get(oauth_login_url(next_url=get_facebook_callback_url(tokenNumber)))
									
class GetFriends:
	
	queue = "*"
	
	@staticmethod	
	def perform(user, limit, offset, token, last=0):
		friendsArray = []
		
		friendsRaw = fql("SELECT uid2 FROM friend WHERE uid1=me() LIMIT %s OFFSET %s" % (limit, offset), token)
		
		for friend in friendsRaw['data']:
			friendsArray.append(friend['uid2'])
		
		redisQueue.enqueue(GetCheckinsPerFriend, user, friendsArray, token, last)
			
						
class GetCheckinsPerFriend:
	
	queue = "*"
		
	@staticmethod	
	def perform(user, friends, token, last):
		
		baseURL = "https://graph.facebook.com/"
		batch = ""
		for friend in friends:
			#while friends.index(friend) != len(friends)-1:
			batch += "{'method':'GET','relative_url':'%s/checkins?limit=3000'}," % friend
			#batch += "{'method':'GET','relative_url':'%s/checkins'}" % friend
		payload = {'batch':'[%s]' % batch, 'method':'post','access_token':token}
		
		r = requests.post(baseURL, data=payload)
		
		dataJSON = json.loads(r.text)
		
		if not last:
			for person in dataJSON:
				redisQueue.enqueue(GetIndividualCheckins, person, user)
		else:
			for person in dataJSON[0:len(dataJSON)-1]:
				redisQueue.enqueue(GetIndividualCheckins, person, user)
			redisQueue.enqueue(GetIndividualCheckins, person, user, 1)

					
class GetIndividualCheckins:
	
	queue = "*"
	
	@staticmethod
	def perform(checkins, user, last=0):
		checkinsJSON = json.loads(checkins['body'])['data']
		
		if not last:
			for checkin in checkinsJSON:
				if 'id' in checkin:
					redisQueue.enqueue(MoveCheckinToDatabase, checkin, user)
				else:
					pass
		else:	
			for checkin in checkinsJSON[0:len(checkinsJSON)-1]:
				if 'id' in checkin:
					redisQueue.enqueue(MoveCheckinToDatabase, checkin, user)
				else:
					pass
			redisQueue.enqueue(MoveCheckinToDatabase, checkinsJSON[-1], user, 1)
			
class MoveCheckinToDatabase:
	
	queue = "*"
	
	@staticmethod
	def perform(checkin, user, last=0):
		checkin_metadata = {}
		collection = db[user]
		
		if collection.find_one({'checkin_id':checkin['id']}):
			pass
		else:
			checkin_metadata['checkin_id'] = checkin['id']
			if 'from' in checkin:
				if 'name' in checkin['from']:
					checkin_metadata['author_name'] = checkin['from']['name']
				if 'id' in checkin['from']:
					checkin_metadata['author_uid'] = checkin['from']['id']
			if 'message' in checkin:
				checkin_metadata['comment'] = checkin['message']
			if 'place' in checkin:
				if 'id' in checkin['place']:
					checkin_metadata['place_id'] = checkin['place']['id']
				if 'name' in checkin['place']:
					checkin_metadata['place_name'] = checkin['place']['name']
					checkin_metadata['place_name_lower'] = checkin_metadata['place_name'].lower()
				if 'location' in checkin['place']:
					if 'city' in checkin['place']['location']:
						checkin_metadata['city'] = checkin['place']['location']['city']
						checkin_metadata['city_lower'] = checkin_metadata['city'].lower()
					if 'country' in checkin['place']['location']:
						checkin_metadata['country'] = checkin['place']['location']['country']
						checkin_metadata['country_lower'] = checkin_metadata['country'].lower()
					if 'state' in checkin['place']['location']:
						checkin_metadata['state_abrv'] = checkin['place']['location']['state']
						checkin_metadata['state_abrv_lower'] = checkin_metadata['state_abrv'].lower()
						if get_state_name(checkin_metadata['state_abrv']):
							checkin_metadata['state'] = get_state_name(checkin_metadata['state_abrv'])
							checkin_metadata['state_lower'] = checkin_metadata['state'].lower()


			collection.insert(checkin_metadata)
					
		if last:
			redisObject.set(user, 1)			
