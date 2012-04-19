import redis
import pymongo
import base64
import simplejson as json
import urllib
import urllib2
from flask import request
import os
import random
import requests

APP_ID = os.environ.get('FACEBOOK_APP_ID')
APP_SECRET = os.environ.get('FACEBOOK_SECRET')

class User:
	def __init__(self, redisServer, db):
		self.redisServer = redisServer
		self.db = db
		self.isAuthenticated = False
		self.name = ''
		self.username = ''
		self.sessID = None
			
	def authenticate(self):
		if not "_sid" in request.cookies or not self.redisServer.exists(request.cookies["_sid"]):
			if request.url_root == self.get_base_url() and request.args.get('code', None):
				self.access_token = self.fbapi_auth(request.args.get('code'))[0]
				self.userInfo = self.get_user_info(self.access_token)
				self.name = self.userInfo['name']
				self.username = self.userInfo['username']
				self.sessID = self.create_session_id()
				self.redisServer.hset(self.sessID, "username", self.username)
				self.redisServer.hset(self.sessID, "first_name", self.userInfo['first_name'])
				self.redisServer.expire(self.sessID, 604800)
			
				self.isAuthenticated = True
		else:
			self.username = self.redisServer.hget(request.cookies["_sid"], "username")
			self.isAuthenticated = True
			
		return self.isAuthenticated
	
	def has_checkins(self):
		if self.username not in self.db.collection_names():
			return False
		else:
			return True
			
	def get_checkins(self):
		friendCount = self.get_friend_count(self.access_token)
		interval = 20
		
		for i in xrange(0, friendCount, interval):
			payload = {}
			requests.post()
			resq.enqueue(GetFriends, user, interval, i, access_token)
	
	def fbapi_auth(self, code):
		params = {'client_id': APP_ID,
				  'redirect_uri': self.get_base_url(),
				  'client_secret': APP_SECRET,
				  'code': code}

		result = self.fbapi_get_string(path=u"/oauth/access_token?", params=params,
								  encode_func=self.simple_dict_serialisation)
		pairs = result.split("&", 1)
		result_dict = {}
		for pair in pairs:
			(key, value) = pair.split("=")
			result_dict[key] = value
		return (result_dict["access_token"], result_dict["expires"])
		
	def fbapi_get_string(self, path, domain=u'graph', params=None, access_token=None,
						 encode_func=urllib.urlencode):
		"""Make an API call"""
		if not params:
			params = {}
		params[u'method'] = u'GET'
		if access_token:
			params[u'access_token'] = access_token

		for k, v in params.iteritems():
			if hasattr(v, 'encode'):
				params[k] = v.encode('utf-8')

		url = u'https://' + domain + u'.facebook.com' + path
		params_encoded = encode_func(params)
		url = url + params_encoded
		result = urllib2.urlopen(url).read()

		return result
		
	def simple_dict_serialisation(self, params):
		return "&".join(map(lambda k: "%s=%s" % (k, params[k]), params.keys()))
		
	def base64_url_encode(self, data):
		return base64.urlsafe_b64encode(data).rstrip('=')
		
	def oauth_login_url(self, preserve_path=True, next_url=None):
		fb_login_uri = ("https://www.facebook.com/dialog/oauth"
						"?client_id=%s&redirect_uri=%s" %
						(APP_ID, next_url))
						

		if app.config['FBAPI_SCOPE']:
			fb_login_uri += "&scope=%s" % ",".join(app.config['FBAPI_SCOPE'])
		return fb_login_uri
		
	def get_user_info(self, token):
		return self.fb_call('me', args={'access_token':token})
		
	def get_base_url(self):
		return 'http://localhost:5000/'
		
	def create_session_id(self):
		x = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+_-'
		sessID = ''.join(random.sample(x, 40)) + '=='
		return sessID
		
	def fql(self, fql, token, args=None):
		if not args:
			args = {}

		args["q"], args["format"], args["access_token"] = fql, "json", token

		return json.loads(
			urllib2.urlopen("https://graph.facebook.com/fql?" +
							urllib.urlencode(args)).read())

	def fb_call(self, call, args=None):
		return json.loads(urllib2.urlopen("https://graph.facebook.com/" + call +
										  '?' + urllib.urlencode(args)).read())
		
	def get_friend_count(self, token):
		return int(fql("SELECT friend_count FROM user WHERE uid=me()", token)['data'][0]['friend_count'])
		
	def logout(self):
		self.redisServer.delete(request.cookies['_sid'])