import os
import simplejson as json
import ast

import pymongo
from flask import Flask, request, redirect, url_for, jsonify, make_response
from mako.template import Template
import redis
import pyres
import requests
from tasks import *
from User import *
from AjaxRequest import *


#CONFIGURE FLASK
app = Flask(__name__)
app.config.from_object(__name__)

if os.environ.get('FACEBOOK_APP_ID'):
	app.config.from_object('conf.Config')
else:
	app.config.from_envvar('MAIN_CONFIG')

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

	
#APP ROUTES	
@app.route('/', methods=['GET', 'POST'])
def welcome():
	user = User(redisServer, db)
	user.authenticate()
	
	if user.isAuthenticated and user.has_checkins():
		r = make_response(redirect('/%s/' % user.username))
	elif user.isAuthenticated:
		user.get_checkins()
		r = make_response(Template(filename='templates/index.html').render(logged_in=True, user=user.username, hasCheckins=False))
	else:
		r = make_response(Template(filename='templates/index.html').render(logged_in=False, user=user.username, hasCheckins=False, loginUrl = oauth_login_url(next_url=user.get_base_url())))
	
	if user.sessID:
		r.set_cookie('_sid', user.sessID)
			
	return r

@app.route('/<user>/', methods=['GET', 'POST'])
def show_user_page(user):
	user = User(redisServer, db)

	if user.authenticate():
		call = AjaxRequest(db, user.username, request.args.get('op', None))
		
		args = [request.args.get('f', None), request.args.get('q', None)]
		
		if args.count(None) is 1:
			args.remove(None)
			
		print args
			
		response = call.make_call(*args)
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
	user = User(redisServer, db)
		
	if user.authenticate() and request.is_xhr:
		call = AjaxRequest(db, user.username, request.args.get('op', None))
		
		args = [request.args.get('f', None), request.args.get('q', None)]
		
		if args.count(None) is not 2:
			args.remove(None)
			
		print args
		#try:
		response = call.make_call(*args)
		#except ValueError:
		#	response = {'error': 'Badly formed query.'}
		#except AttributeError:
		#	response = {'error': 'Invalid operation.'}
	else:
		response['error'] = "Error validating request."
	
	return jsonify(response)	
	
@app.route('/callback/', methods=['GET', 'POST'])
def callback():
	if request.method == "GET" and request.args.get('code'):
		code = request.args.get('code')
		return redirect('/')

@app.route('/close/', methods=['GET', 'POST'])
def close():
	return render_template('templates/close.html')
	
			
@app.route('/logout/', methods=['GET', 'POST'])
def logout():
	user = User(redisServer, db)
	user.logout()
	
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