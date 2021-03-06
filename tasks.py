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

redisServer = redis.Redis(
						host=environ.get("REDIS_HOST"),
						port=int(environ.get("REDIS_PORT")),
						password=environ.get("REDIS_PASSWORD")
						)
resq = pyres.ResQ(redisServer)



def oauth_login_url(preserve_path=True, next_url=None):
	fb_login_uri = ("https://www.facebook.com/dialog/oauth"
					"?client_id=%s&redirect_uri=%s" %
					(APP_ID, next_url))

	if environ.get('FBAPI_SCOPE'):
		fb_login_uri += "&scope=%s" % environ.get('FBAPI_SCOPE')
	return fb_login_uri
	
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

class PerformLater:
	queue = "perform_later"
	
	@staticmethod
	def perform(klass, *args):
		resq.enqueue(klass, args)
		
		
class GetFriends:
	
	queue = "*"
	
	@staticmethod	
	def perform(user, limit, offset, token):
		friendsArray = []
		
		friendsRaw = fql("SELECT uid2 FROM friend WHERE uid1=me() LIMIT %s OFFSET %s" % (limit, offset), token)
		
		for friend in friendsRaw['data']:
			friendsArray.append(friend['uid2'])
		
		resq.enqueue(GetCheckinsPerFriend, user, friendsArray, token)
			
						
class GetCheckinsPerFriend:
	
	queue = "*"
		
	@staticmethod	
	def perform(user, friends, token):
		
		baseURL = "https://graph.facebook.com/"
		batch = ""
		friendArray = []
		for friend in friends:
			#while friends.index(friend) != len(friends)-1:
			batch += "{'method':'GET','relative_url':'%s/checkins?limit=3000'}," % friend
			friendArray.append(friend)
		payload = {'batch':'[%s]' % batch, 'method':'post','access_token':token}
		
		r = requests.post(baseURL, data=payload)
		
		dataJSON = json.loads(r.text)
		
		if dataJSON[0]['body'][0:8] != "{\"error\"":
			for person in dataJSON:
				resq.enqueue(GetIndividualCheckins, person, user, friendArray[dataJSON.index(person)])
		else:
			resq.enqueue(PerformLater, "GetCheckinsPerFriend", user, friends, token)

					
class GetIndividualCheckins:
	
	queue = "*"
	
	@staticmethod
	def perform(checkins, user, friend):
		checkinsJSON = json.loads(checkins['body'])['data']
		
		for checkin in checkinsJSON:
			if 'id' in checkin:
				resq.enqueue(MoveCheckinToDatabase, checkin, user, friend)
			else:
				pass
			
class MoveCheckinToDatabase:
	
	queue = "*"
	
	@staticmethod
	def perform(checkin, user, friend):
		checkin_metadata = {}
		collection = db[user]
		
		if collection.find_one({'checkin_id':checkin['id']}):
			pass
		else:
			checkin_metadata['checkin_id'] = checkin['id']
			if 'id' in checkin['from'] and checkin['from']['id'] == friend:
				checkin_metadata['author_name'] = checkin['from']['name']
				checkin_metadata['author_uid'] = checkin['from']['id']
			elif 'tags' in checkin:
				for personTagged in checkin['tags']:
					if personTagged['id'] == friend:
						checkin_metadata['author_name'] = personTagged['name']
						checkin_metadata['author_uid'] = personTagged['id']
						checkin_metadata['tagged_by_name'] = checkin['from']['name']
						checkin_metadata['tagged_by_uid'] = checkin['from']['id']
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
