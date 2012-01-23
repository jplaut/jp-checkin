import base64
import os
import os.path
import simplejson as json
import urllib
import urllib2
from collections import defaultdict

import pymongo
from flask import Flask, request, redirect, url_for
from mako.template import Template

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_object('conf.Config')

if os.environ.get('FACEBOOK_APP_ID'):
	APP_ID = os.environ.get('FACEBOOK_APP_ID')
	APP_SECRET = os.environ.get('FACEBOOK_SECRET')
else:
	APP_ID = app.config.get('FACEBOOK_APP_ID')
	APP_SECRET = app.config.get('FACEBOOK_SECRET')


def connect_to_database():
	DBPATH=os.environ.get('MONGODBPATH')
	DBNAME=os.environ.get('MONGODBDATABASE')
	connection = pymongo.Connection(DBPATH)
	db = connection.app2412171
	return db.data

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
			  'redirect_uri': get_home(),
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
	
def aggregate_checkins(token):
	return fql("{\"query1\":\"SELECT uid2 FROM friend WHERE uid1=me()\",\"query2\":\"SELECT page_id, author_uid FROM checkin WHERE author_uid IN (SELECT uid2 FROM #query1)\"}", token)

def sort_checkins(checkins_unsorted):
	checkins_tuple=[]
	for checkin in checkins_unsorted:
		checkins_tuple.append((checkin['page_id'], checkin['author_uid']))

	checkins_sorted={}
	d = defaultdict(list)

	for k, v in checkins_tuple:
		if not str(v) in d[str(k)]:
			d[str(k)].append(str(v))

	return dict(d)

def get_username(token):
	return fb_call('me', args={'access_token':token})['username']


@app.route('/', methods=['GET', 'POST'])
def welcome():
	if request.args.get('code', None):
		access_token = fbapi_auth(request.args.get('code'))[0]
		username = get_username(access_token)
		return Template(filename='templates/index.html').render(username=username)
	else:
		return Template(filename='templates/welcome.html').render()
		
@app.route('/login/', methods=['GET', 'POST'])
def login():
	print oauth_login_url(next_url=get_home())
	return redirect(oauth_login_url(next_url=get_home()))
	
@app.route('/<username>/')
def index(username):
		#checkins = aggregate_checkins(access_token)
		#checkins_sorted = sort_checkins(checkins['data'][1]['fql_result_set'])

		return Template(filename='templates/index.html').render(username=username)

@app.route('/close/', methods=['GET', 'POST'])
def close():
	return render_template('templates/close.html')

@app.route('/test/', methods=['GET', 'POST'])
def test():
	print "YES!"
	return None
	
		
@app.route('/fb/callback/', methods=['GET', 'POST'])
def handle_facebook_requests():
	pass
	

if __name__ == '__main__':
	port = int(os.environ.get("PORT", 5000))
	if APP_ID and APP_SECRET:
		app.run(host='0.0.0.0', port=port)
	else:
		print 'Cannot start application without Facebook App Id and Secret set'