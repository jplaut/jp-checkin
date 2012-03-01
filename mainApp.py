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

#APP METHODS
def oauth_login_url(preserve_path=True, next_url=None):
	fb_login_uri = ("https://www.facebook.com/dialog/oauth"
					"?client_id=%s&redirect_uri=%s" %
					(APP_ID, next_url))

	if app.config['FBAPI_SCOPE']:
		fb_login_uri += "&scope=%s" % ",".join(app.config['FBAPI_SCOPE'])
	return fb_login_uri


def simple_dict_serialisation(params):
	return "&".join(map(lambda k: "%s=%s" % (k, params[k]), params.keys()))


def base64_url_encode(data):
	return base64.urlsafe_b64encode(data).rstrip('=')


def fbapi_get_string(path, domain=u'graph', params=None, access_token=None,
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


def fbapi_auth(code):
	params = {'client_id': APP_ID,
			  'redirect_uri': get_base_url(),
			  'client_secret': APP_SECRET,
			  'code': code}

	result = fbapi_get_string(path=u"/oauth/access_token?", params=params,
							  encode_func=simple_dict_serialisation)
	pairs = result.split("&", 1)
	result_dict = {}
	for pair in pairs:
		(key, value) = pair.split("=")
		result_dict[key] = value
	return (result_dict["access_token"], result_dict["expires"])


def fbapi_get_application_access_token(id):
	token = fbapi_get_string(
		path=u"/oauth/access_token",
		params=dict(grant_type=u'client_credentials', client_id=id,
					client_secret=APP_SECRET, domain=u'graph'))

	token = token.split('=')[-1]
	if not str(id) in token:
		print 'Token mismatch: %s not in %s' % (id, token)
	return token


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

def get_user_info(token):
	return fb_call('me', args={'access_token':token})

def get_friend_count(token):
	return int(fql("SELECT friend_count FROM user WHERE uid=me()", token)['data'][0]['friend_count'])

def get_next_field(field, query=""):
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
		
def create_session_id():
	x = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+_-'
	sessID = ''.join(random.sample(x, 40)) + '=='
	return sessID
	
def return_browse_data(user, operation, field, query):
	collection = db[user]
	body = {}
	body['data'] = {}
	body['data']['links'] = ""
	
	if operation == "friends":
		distinct = "author_name"
	else:
		distinct = get_next_field(field, query)
	
	for elem in sorted(collection.find({field:query}).distinct(distinct)):
		body['data']['links'] += "<li><a id=\"browseLink\" href=\"#\" operation=\"%s\" field=\"%s\" query=\"%s\">%s</a></li>" % (operation, get_next_field(field, query), elem, elem)
	
	if operation == "places":
		body['data']['friendsLink'] = "<a id=\"browseLink\" href=\"#\" operation=\"friends\" field=\"%s\" query=\"%s\">See who's been here.</a></li>" % (field, query)
		
	return body	
		
#APP ROUTES	
@app.route('/', methods=['GET', 'POST'])
def welcome():
	
	if not "_sid" in request.cookies or not redisServer.exists(request.cookies["_sid"]):
		if request.args.get('code', None):
			access_token = fbapi_auth(request.args.get('code'))[0]
			userInfo = get_user_info(access_token)
			name = userInfo['name']
			user = userInfo['username']
			sessID = create_session_id()
			
			redisServer.hset(sessID, "username", user)
			redisServer.hset(sessID, "first_name", userInfo['first_name'])
			redisServer.expire(sessID, 604800)
			
			if user not in db.collection_names():
				redisServer.set(user+":status", 0)
				
				#QUEUE UP CHECKIN TASKS
				friendCount = get_friend_count(access_token)
				interval = 20
		
				if friendCount%interval == 0:
					lastOffset = friendCount-interval
				else:
					lastOffset = friendCount-friendCount%interval
		
				for i in xrange(0, lastOffset, interval):
					resq.enqueue(GetFriends, user, interval, i, access_token)
				resq.enqueue(GetFriends, user, interval, lastOffset, access_token, 1)
				
				#RETURN LOADING SCREEN
				r = make_response(Template(filename='templates/index.html').render(logged_in=True, user=user, status=0))
			else:
				#REDIRECT TO MAIN USER PAGE
				r = make_response(redirect('/%s/' % user))
			
			
			r.set_cookie("_sid", sessID, max_age=604800)
			return r
			
		else:
			#RETURN GENERIC NON-LOGGED IN TEMPLATE
			return Template(filename='templates/index.html').render(logged_in=False, facebook_auth_url=oauth_login_url(next_url=get_base_url()))
		
	else:
		user = redisServer.hget(request.cookies["_sid"], "username")
		return redirect('/%s/' % user)


@app.route('/close/', methods=['GET', 'POST'])
def close():
	return render_template('templates/close.html')

@app.route('/<user>/', methods=['GET', 'POST'])
def show_user_page(user):
	if request.cookies['_sid'] and user == redisServer.hget(request.cookies['_sid'], "username"):
		collection = db[user]
		countries = sorted(collection.distinct("country"))
		firstName = redisServer.hget(request.cookies['_sid'], "first_name")
	
		if None in countries:
			countries.remove(None)
	
		return Template(filename='templates/user.html').render(logged_in=True, user=user, name=firstName, countries=countries, baseURL=get_base_url())
	
	else:
		return Template(filename='templates/user.html').render(logged_in=False, baseURL=get_base_url())
	
@app.route('/check_status/', methods=['POST'])
def check_status():
	user = request.args.get('user', None)
	body = {}
	
	if request.cookies['_sid'] and user == redisServer.hget(request.cookies['_sid'], "username"):
		body['status'] = redisServer.hget(user, "status")
	else:
		body['error'] = "Error validating request."
	
	return jsonify(body)
	
@app.route('/ajax/', methods=['POST'])
def return_browsing_data():
	if request.is_xhr and request.cookies['_sid'] and redisServer.exists(request.cookies['_sid']):
		operation = request.args.get('op', None)
		user = redisServer.hget(request.cookies['_sid'], "username")
		body = {}
		
		if operation == 'places' or operation == 'friends':
			try:
				body = return_browse_data(user, operation, request.args.get('field', None), request.args.get('q', None))
			except TypeError:
				body['error'] = "Badly formed query."
				
		elif operation == 'search':
			pass
			
		else:
			body['error'] = "Invalid operation."
			
	else:
		body['error'] = "Error validating request."
	
	return jsonify(body)	
	
@app.route('/callback/', methods=['GET', 'POST'])
def callback():
	if request.method == "GET" and request.args.get('code'):
		code = request.args.get('code')
		return redirect(get_base_url() + '?code=%s' % code)
		
@app.route('/logout/', methods=['GET', 'POST'])
def logout():
	if request.cookies['_sid'] and redisServer.exists(request.cookies['_sid']):
		redisServer.delete(request.cookies['_sid'])
		
		return redirect('/')
		
	else:
		return redirect('/error/')
		
@app.route('/error/', methods=['GET'])
def show_error_page():
	return Template(filename='templates/error.html').render()
	
	
if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))
	if APP_ID and APP_SECRET:
		app.run(host='0.0.0.0', port=port)
	else:
		print 'Cannot start application without Facebook App Id and Secret set'