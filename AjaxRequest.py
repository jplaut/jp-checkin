import redis
import pymongo
import unidecode
from flask import request

class AjaxRequest:
	def __init__(self, db, user, operation):
		if (operation):
			self.operation = operation
		else:
			self.operation = 'places'
			
		self.collection = db[user]
		
	def make_call(self, *args):
		return getattr(self, self.operation)(*args)
		
	def places(self, field, query):
		body = {'data':{'places':''}}
		
		# If viewing main user page, return generic countries list
		if not field and not query:
			for country in sorted(self.__fetch("", "", "country")):
				if country == "None":
					continue
				else:
					body['data']['places'] += "<li><a id=\"browseLink\" href=\"?op=places&f=country&q=%s\">%s</a></li>" % (country, country)
		
		# If viewing specific location, return places for that location
		elif field and query:
			nextField = self.get_next_field(field, query)
			if nextField == "place_name":
				operation = "friends"
			else:
				operation = "places"
			
			for elem in sorted(self.__fetch(field, query, str(nextField))):
				body['data']['places'] += "<li><a id=\"browseLink\" href=\"?op=%s&f=%s&q=%s\">%s</a></li>" % (operation, nextField, elem, elem)

			body['data']['friendsLink'] = "<a id=\"browseLink\" href=\"?op=friends&f=%s&q=%s\">See who's been here.</a>" % (field, query)
		
		# If query is incorrect, return an error
		else:
			body = {'error': 'Badly formed query.'}
			
		return body
		
	def friends(self, field, query):
		body = {'data':{'friends': ''}}
		
		for elem in sorted(self.__fetch(field, query, 'author_name')):
			body['data']['friends'] += "<li><a id=\"browseLink\" href=\"?op=checkins&q=%s\">%s</a></li>" % (elem, elem)
			
		return body
		
	def checkins(self, query):
		body = {'data':{'checkins':[]}}
		body['data']['title'] = """
					<div class=\"popup_title\">
						<a href=\"http://www.facebook.com/%s\" target=\"_blank\">%s</a>
					</div>
				""" % (self.collection.find_one({'author_name':query}, ['author_uid'])['author_uid'], query)
		
		for elem in self.__fetch('author_name', query, None, ['city','country', 'state', 'comment', 'place_name', 'place_id', 'author_uid']):
			checkin = """
			<li>
				<div class=\"location\">
					<a href=\"http://www.facebook.com/%s\" target=\"_blank\">%s</a><br />
				""" % (elem['place_id'], elem['place_name']) 
			
			if 'city' in elem:
				checkin += "%s<br />" % elem['city']
			if 'state' in elem:
				checkin += "%s<br />" % elem['state']
			if 'country' in elem:
				checkin += "%s<br />" % elem['country']
			if 'comment' in elem:
				checkin += "%s<br />" % elem['comment']
			
			checkin += "</div></li>"
			
			body['data']['checkins'].append(checkin)

		return body
		
	def search(self, query):
		pass
		
	def __fetch(self, field="", query="", distinct="", fields=[]):
		if field and query and distinct:
			return self.collection.find({field:query}, fields).distinct(distinct)
		elif field and query:
			return self.collection.find({field:query}, fields)
		elif distinct:
			return self.collection.distinct(distinct)
		else:
			return None
	
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