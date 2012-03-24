import base64
import os
import simplejson as json
import urllib
import urllib2
from collections import defaultdict
import math
import random
import time

import pymongo
from flask import Flask, request, redirect, url_for, jsonify, make_response
from mako.template import Template
import redis
import pyres
import requests 
from tasks import *

#CONFIGURE FLASK
app = Flask(__name__)
app.config.from_object(__name__)

if os.environ.get('FACEBOOK_APP_ID'):
	app.config.from_object('conf.Config')
else:
	app.config.from_envvar('MAIN_CONFIG')

APP_ID = os.environ.get('FACEBOOK_APP_ID')
APP_SECRET = os.environ.get('FACEBOOK_SECRET')

#CONFIGURE MONGODB
DBPATH=environ.get('MONGODBPATH')
DBNAME=environ.get('MONGODBDATABASE')
connection = pymongo.Connection(DBPATH)
db = connection[DBNAME]

#CONFIGURE REDIS
redisServer = redis.Redis(
						host=environ.get("REDIS_HOST"),
						port=int(environ.get("REDIS_PORT")),
						password=environ.get("REDIS_PASSWORD")
						)
resq = pyres.ResQ(redisServer)

class User:
	def __init__(self):
		self.isAuthenticated = False
		self.name = ''
		self.username = ''
		self.sessID = None
			
	def authenticate(self):
		if not "_sid" in request.cookies or not redisServer.exists(request.cookies["_sid"]):
			if request.url_root == get_base_url() and request.args.get('code', None):
				self.access_token = self.fbapi_auth(request.args.get('code'))[0]
				self.userInfo = self.get_user_info(self.access_token)
				self.name = self.userInfo['name']
				self.username = self.userInfo['username']
				self.sessID = self.create_session_id()
				redisServer.hset(self.sessID, "username", self.username)
				redisServer.hset(self.sessID, "first_name", self.userInfo['first_name'])
				redisServer.expire(self.sessID, 604800)
			
				self.isAuthenticated = True
		else:
			self.username = redisServer.hget(request.cookies["_sid"], "username")
			self.isAuthenticated = True
			
		return self.isAuthenticated
	
	def has_checkins(self):
		if self.username not in db.collection_names():
			return False
		else:
			return True
			
	def get_checkins(self):
		friendCount = self.get_friend_count(self.access_token)
		interval = 20

		for i in xrange(0, friendCount, interval):
			resq.enqueue(GetFriends, user, interval, i, access_token)
	
	def fbapi_auth(self, code):
		params = {'client_id': APP_ID,
				  'redirect_uri': get_base_url(),
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
		return fb_call('me', args={'access_token':token})
		
	def create_session_id(self):
		x = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+_-'
		sessID = ''.join(random.sample(x, 40)) + '=='
		return sessID
		
	def get_friend_count(self, token):
		return int(fql("SELECT friend_count FROM user WHERE uid=me()", token)['data'][0]['friend_count'])
		
	def logout(self):
		redisServer.delete(request.cookies['_sid'])

class AjaxRequest:
	def __init__(self, user, operation):
		if operation:
			self.operation = operation
		else:
			self.operation = 'places'
			
		self.collection = db[user]
		
	def make_call(self, *args):
		
		for arg in args:
			if not arg:
				list(args).remove(arg)
		
		return getattr(self, self.operation)(*args)
		
	def places(self, field, query):
		body = {'data':{'links':''}}
		
		if not field and not query:
			for country in sorted(self.collection.distinct("country")):
				if country == "None":
					continue
				else:
					body['data']['links'] += "<li><a id=\"browseLink\" href=\"?op=browse&f=state&q=%s\" op=\"places\" f=\"country\" q=\"%s\">%s</a></li>" % (country, country, country)
		elif field and query:
			nextField = self.get_next_field(field, query)

			for elem in sorted(self.collection.find({field:query}).distinct(nextField)):
				body['data']['links'] += "<li><a id=\"browseLink\" href=\"?op=places&f=%s&q=%s\" op=\"places\" f=\"%s\" q=\"%s\">%s</a></li>" % (nextField, elem, nextField, elem, elem)
	
			body['data']['friendsLink'] = "<a id=\"browseLink\" href=\"?op=friends&f=%s&q=%s\" op=\"friends\" f=\"%s\" q=\"%s\">See who's been here.</a>" % (field, query, field, query)
		
		else:
			body = {'error': 'Badly formed query.'}
			
		return body
		
	def friends(self, field, query):
		body = {'data':{'links': ''}}
		
		for elem in sorted(self.collection.find({field:query}).distinct('author_name')):
			body['data']['links'] += "<li><a id=\"browseLink\" href=\"?op=checkins&q=%s\" op=\"checkins\" q=\"%s\">%s</a></li>" % (elem, elem, elem)
			
		return body
		
	def checkins(self, field, query):
		body = {'data':{'checkins':[]}}

		for elem in self.collection.find({'author_name':query}, ['city','country', 'state', 'comment', 'place_name', 'place_id', 'author_uid']):
			body['data']['checkins'].append("""
			<div class="checkin">
				<div class="popup_title"><a href="http://www.facebook.com/%s" target="_blank">%s</a></div>
				<div class="location">
					<a href="http://www.facebook.com/%s" target="_blank">%s</a><br />
					%s<br />
					%s<br />
					%s<br />
				</div>
			</div>
		""" % (elem['author_uid'], query, elem['place_id'], elem['place_name'], elem['city'], elem['state'], elem['country']))

		return body
		
	def search(self, query):
		pass
	
	def get_next_field(self, field, query=""):
		fields = [
				"country",
				"state",
				"city",
				"place_name"	
				]
	
		if field == "country":
			if query == "United States":
				return "state"
			else:
				return "city"
		else:
			if field in fields:
				return fields[fields.index(field)+1]
			else:
				return None
				
				
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

def get_home():
	return 'http://' + request.host + '/'

def get_base_url():
	return 'http://localhost:5000/'
	
	
#APP ROUTES	
@app.route('/', methods=['GET', 'POST'])
def welcome():
	user = User()
	user.authenticate()
	
	if user.isAuthenticated and user.has_checkins():
		r = make_response(redirect('/%s/' % user.username))
	elif user.isAuthenticated:
		user.get_checkins()
		r = make_response(Template(filename='templates/index.html').render(logged_in=True, user=user.username, hasCheckins=False))
	else:
		r = make_response(Template(filename='templates/index.html').render(logged_in=False, user=user.username, hasCheckins=False, loginUrl = oauth_login_url(next_url=get_base_url())))
	
	if user.sessID:
		r.set_cookie('_sid', user.sessID)
			
	return r

@app.route('/close/', methods=['GET', 'POST'])
def close():
	return render_template('templates/close.html')

@app.route('/<user>/', methods=['GET', 'POST'])
def show_user_page(user):
	user = User()

	if user.authenticate():
		call = AjaxRequest(user.username, request.args.get('op', None))
		try:
			response = call.make_call(request.args.get('f', None), request.args.get('q', None))	
		except (ValueError, AttributeError):
			response = {'error': 'Error serving request. Please check URL and try again.'}
	else:
		response = {'error': 'Error authenticating user. Please try <a href=\"%s?redirect=true\">logging in</a> again.' % get_base_url()}
			
		
	return Template(filename='templates/user.html').render(user=user.username, name=user.name, links=response)

	
@app.route('/check_status/', methods=['POST'])
def check_status():
	user = request.args.get('user', None)
	body = {}
	
	if request.cookies['_sid'] and user == redisServer.hget(request.cookies['_sid'], "username"):
		for task in redisServer.lrange('resque:queue:*', 0, redisServer.llen('resque:queue:*')):
			if ast.literal_eval(task)['args'][0] == user:
				return jsonify(status=0)
			else:
				return jsonify(status=1)
	else:
		return jsonify(error="Error validating request.")
	
@app.route('/ajax/', methods=['POST'])
def return_browsing_data():
	user = User()
	
	if user.authenticate() and request.is_xhr:
		call = AjaxRequest(user.username, request.args.get('op', None))
		try:
			response = call.make_call(str(request.args.get('f', None)), str(request.args.get('q', None)))
		except ValueError:
			response = {'error': 'Badly formed query.'}
		except AttributeError:
			response = {'error': 'Invalid operation.'}
	else:
		response['error'] = "Error validating request."
	
	return jsonify(response)	
	
@app.route('/callback/', methods=['GET', 'POST'])
def callback():
	if request.method == "GET" and request.args.get('code'):
		code = request.args.get('code')
		return redirect(get_base_url() + '?code=%s' % code)
		
@app.route('/logout/', methods=['GET', 'POST'])
def logout():
	user = User()
	user.logout()
	
	if request.args.get('redirect', None) == 'true':
		return redirect(oauth_login_url(next_url=get_base_url()))
	else:
		return redirect('/')
		
@app.route('/error/', methods=['GET'])
def show_error_page():
	return Template(filename='templates/error.html').render()
	
	
if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))
	if APP_ID and APP_SECRET:
		app.run(host='0.0.0.0', port=port)
	else:
		print 'Cannot start application without Facebook App Id and Secret set'