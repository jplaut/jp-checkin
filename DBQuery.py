class DBQuery:
	def __init__(self, db):
		self.db = db
		
	def fetch(self, field="", query="", distinct=""):
		