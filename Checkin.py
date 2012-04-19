class DBQuery:
	def __init__(self, db, field="", query="", distinct=""):
		self.db = db
		self.field = field
		self.query = query
		self.distinct = distinct
		
	def fetch(self):
		