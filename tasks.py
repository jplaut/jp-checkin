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
											

class GetNewToken:
	queue = "*"
	
	@staticmethod
	def perform(tokenNumber):
		r = requests.get(oauth_login_url(next_url=get_facebook_callback_url(tokenNumber)))
									
class GetFriends:
	
	queue = "*"
	
	@staticmethod	
	def perform(user, limit, offset, token):
		friendsArray = []
		
		friendsRaw = fql("SELECT uid2 FROM friend WHERE uid1=me() LIMIT %s OFFSET %s" % (limit, offset), token)
		
		for friend in friendsRaw['data']:
			friendsArray.append(friend['uid2'])
		
		redisQueue.enqueue(AggregateCheckins, user, friendsArray, token)
			
						
class AggregateCheckins:
	
	queue = "*"
		
	@staticmethod	
	def perform(user, friends, token):
		
		baseURL = "https://graph.facebook.com/"
		batch = ""
		for friend in friends:
			#while friends.index(friend) != len(friends)-1:
			batch += "{'method':'GET','relative_url':'%s/checkins?limit=3000'}," % friend
			#batch += "{'method':'GET','relative_url':'%s/checkins'}" % friend
		payload = {'batch':'[%s]' % batch, 'method':'post','access_token':token}
		
		r = requests.post(baseURL, data=payload)
		
		dataJSON = json.loads(r.text)
		
		
		for person in dataJSON:
			for checkin in json.loads(person['body'])['data']:
				if 'id' in checkin:
					redisQueue.enqueue(MoveCheckinToDatabase, checkin, user)
				else:
					pass
				
class MoveCheckinToDatabase:
	
	queue = "*"
	
	@staticmethod
	def perform(checkin, user):
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
				if 'location' in checkin['place']:
					if 'city' in checkin['place']['location']:
						checkin_metadata['city'] = checkin['place']['location']['city']
					if 'country' in checkin['place']['location']:
						checkin_metadata['country'] = checkin['place']['location']['country']
					if 'state' in checkin['place']['location']:
						checkin_metadata['state'] = checkin['place']['location']['state']
				if 'id' in checkin['place']:
					checkin_metadata['place_id'] = checkin['place']['id']
				if 'name' in checkin['place']:
					checkin_metadata['place_name'] = checkin['place']['name']

				collection.insert(checkin_metadata)
					
					
