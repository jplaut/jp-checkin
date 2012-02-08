from os import environ
import pymongo
import urllib
import urllib2
from collections import defaultdict
import redis
import myres
import simplejson as json

DBPATH=environ.get('MONGODBPATH')
DBNAME=environ.get('MONGODBDATABASE')
connection = pymongo.Connection(DBPATH)
db = connection[DBNAME]

redisServer = environ.get("REDIS_QUEUE_SERVER")
redisPassword = environ.get("REDIS_QUEUE_PASSWORD")

redisQueue = myres.ResQ(server=redisServer, password=redisPassword)

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
									
class GetCheckinMetadata:
	
	def __init__(self):
		
		queue = "get_checkin_metadata"
		
	@staticmethod
	def perform(checkin_id, user, token):
		checkin_metadata = {}
		collection = db[user]
		
		checkin_metadata_all = fb_call(str(checkin_id), args={'access_token': token})
		
		if 'from' in checkin_metadata_all:
			if 'name' in checkin_metadata_all['from']:
				checkin_metadata['author_name'] = checkin_metadata_all['from']['name']
			if 'id' in checkin_metadata_all['from']:
				checkin_metadata['author_uid'] = checkin_metadata_all['from']['id']
		if 'message' in checkin_metadata_all:
			checkin_metadata['comment'] = checkin_metadata_all['message']
		if 'place' in checkin_metadata_all:
			if 'id' in checkin_metadata_all['place']:
				checkin_metadata['place_id'] = checkin_metadata_all['place']['id']
			if 'name' in checkin_metadata_all['place']:
				checkin_metadata['place_name'] = checkin_metadata_all['place']['name']
			if 'location' in checkin_metadata_all['place']:
				checkin_metadata['place_city'] = checkin_metadata_all['place']['location']
		
		collection.insert(checkin_metadata)
					
class AggregateCheckins:
	
	queue = "aggregate_checkins"
		
	@staticmethod	
	def perform(user, token, limit, offset):
		
		query1 = "\"query1\":\"SELECT uid2 FROM friend WHERE uid1=me() LIMIT %s OFFSET %s\"" % (limit, offset)
		query2 = "\"query2\":\"SELECT checkin_id FROM checkin WHERE author_uid IN (SELECT uid2 FROM #query1)\""
		
		checkins = fql("{%s, %s}" % (query1, query2), token)['data'][1]['fql_result_set']
		
		for checkin in checkins:
			redisQueue.enqueue(GetCheckinMetadata, checkin['checkin_id'], user, token)
	