import base64
import os
import os.path
import simplejson as json
import urllib
import urllib2

from flask import Flask, request, redirect
from mako.template import Template

app = Flask(__name__)
if os.environ.get('FACEBOOK_APP_ID'):
    FBAPI_APP_ID = os.environ.get('FACEBOOK_APP_ID')
    FBAPI_APP_SECRET = os.environ.get('FACEBOOK_SECRET')
else:
    FBAPI_APP_ID = app.config['FBAPI_APP_ID']
    FBAPI_APP_SECRET = FBAPI_APP_SECRET


def oauth_login_url(preserve_path=True, next_url=None):
    fb_login_uri = ("https://www.facebook.com/dialog/oauth"
                    "?client_id=%s&redirect_uri=%s" %
                    (FBAPI_APP_ID, get_home()))

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
    params = {'client_id': FBAPI_APP_ID,
              'redirect_uri': get_home(),
              'client_secret': FBAPI_APP_SECRET,
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
                    client_secret=app.config['FB_APP_SECRET']),
        domain=u'graph')

    token = token.split('=')[-1]
    if not str(id) in token:
        print 'Token mismatch: %s not in %s' % (id, token)
    return token


def fql(fql, token, args=None):
    if not args:
        args = {}

    args["query"], args["format"], args["access_token"] = fql, "json", token
    return json.loads(
        urllib2.urlopen("https://api.facebook.com/method/fql.query?" +
                        urllib.urlencode(args)).read())


def fb_call(call, args=None):
    return json.loads(urllib2.urlopen("https://graph.facebook.com/" + call +
                                      '?' + urllib.urlencode(args)).read())

app.config.from_object(__name__)
app.config.from_object('conf.Config')


def get_home():
    return 'http://' + request.host + '/'


@app.route('/', methods=['GET', 'POST'])
def index():
    print get_home()
    if request.args.get('code', None):
        access_token = fbapi_auth(request.args.get('code'))[0]

        checkins = fb_call('me/friends', args={'access_token': access_token})

        return Template(filename='index.html').render(checkins=checkins)

    else:
        print oauth_login_url(next_url=get_home())
        return redirect(oauth_login_url(next_url=get_home()))

@app.route('/close/', methods=['GET', 'POST'])
def close():
    return render_template('close.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    if app.config.get('FBAPI_APP_ID') and app.config.get('FBAPI_APP_SECRET'):
        app.run(host='0.0.0.0', port=port)
    else:
        print 'Cannot start application without Facebook App Id and Secret set'
