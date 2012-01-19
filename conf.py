import os


class Config(object):
    DEBUG = True
    TESTING = False
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
    FBAPI_SCOPE = ['user_checkins', 'friends_checkins']
    FBAPI_APP_ID = "331389096895249"
    FBAPI_APP_SECRET = "2f0ab20496fc3b232d0740694dd18d2e"
