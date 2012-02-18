import base64
import os
import simplejson as json
import urllib
import urllib2
from collections import defaultdict
import math

import pymongo
from flask import Flask, request, redirect, url_for, jsonify
from mako.template import Template
import redis
import pyres
import requests 
from tasks import *

app = Flask(__name__)
app.config.from_object(__name__)

if os.environ.get('FACEBOOK_APP_ID'):
	app.config.from_object('conf.Config')
else:
	app.config.from_envvar('MAIN_CONFIG')

APP_ID = os.environ.get('FACEBOOK_APP_ID')
APP_SECRET = os.environ.get('FACEBOOK_SECRET')

redisHost = os.environ.get("REDIS_QUEUE_HOST")
redisPort = int(os.environ.get("REDIS_QUEUE_PORT"))
redisPassword = os.environ.get("REDIS_QUEUE_PASSWORD")

redisObject = redis.Redis(host=redisHost, port=redisPort, password=redisPassword)

redisQueue = pyres.ResQ(redisObject)

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
			  'redirect_uri': get_facebook_callback_url(),
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
	
def get_facebook_callback_url():
	return 'http://jp-checkin.herokuapp.com/'

def get_username(token):
	return fb_call('me', args={'access_token':token})['username']

def get_friend_count(token):
	return int(fql("SELECT friend_count FROM user WHERE uid=me()", token)['data'][0]['friend_count'])
	
@app.route('/', methods=['GET', 'POST'])
def welcome():
	
	if request.args.get('code', None):
		access_token = fbapi_auth(request.args.get('code'))[0]
		
		if request.args.get('token_number', None):
			tokenNumber = request.args.get('token_number')
		else:
			tokenNumber = 0
			
		username = get_username(access_token)
		friendCount = get_friend_count(access_token)
		tokenInterval = 500
		friendOffset = tokenInterval * tokenNumber
		numberOfTokens = int(math.ceil(friendCount/float(tokenInterval)))
		friendInterval = 20
		lastCall = friendOffset+tokenInterval-friendInterval
		
		for j in xrange(numberOfTokens):
			if j<numberOfTokens-1:
				for i in xrange(tokenInterval*j, tokenInterval*(j+1), friendInterval):
					redisQueue.enqueue(GetFriends, username, friendInterval, i, access_token)
			else:
				for i in xrange(tokenInterval*j, tokenInterval*(j+1)-friendInterval, friendInterval):
					redisQueue.enqueue(GetFriends, username, friendInterval, i, access_token)
				redisQueue.enqueue(GetFriends, username, friendInterval, i, access_token, 1)
			
			redisQueue.enqueue(GetNewToken, tokenNumber+1)
		
			
		return Template(filename='templates/index.html').render(name=username)
	else:
		return redirect(oauth_login_url(next_url=get_facebook_callback_url()))
		
@app.route('/login/', methods=['GET', 'POST'])
def login():
	print oauth_login_url(next_url=get_home())
	return redirect(oauth_login_url(next_url=get_facebook_callback_url()))

@app.route('/close/', methods=['GET', 'POST'])
def close():
	return render_template('templates/close.html')

@app.route('/_checkstatus/', methods=['POST'])
def check_status():
	user = request.args.get('user')
	
	if redisObject.get(user) == 1:
		redisObject.delete(user)
		return jsonify(state=1)
	else:
		return jsonify(state=0)
		
@app.route('/callback/', methods=['GET', 'POST'])
def callback():
	if request.method == "GET" and request.args.get('code'):
		code = request.args.get('code')
		return redirect(get_facebook_callback_url() + '?code=%s' % code)
		

if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))
	if APP_ID and APP_SECRET:
		app.run(host='0.0.0.0', port=port)
	else:
		print 'Cannot start application without Facebook App Id and Secret set'