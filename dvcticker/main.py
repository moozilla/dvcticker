import webapp2
from google.appengine.api import urlfetch
import json
from PIL import Image, ImageDraw, ImageFont
from google.appengine.api import memcache
import StringIO
import jinja2
import os
from decimal import * #used fixed point math for better accuracy
from google.appengine import runtime # for catching DeadlineExceededError
from google.appengine.api import urlfetch_errors # "

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

def urlfetch_cache(url,exchange):
    # fetches a url, but using memcache to not hammer the exchanges server
    data = memcache.get(url)
    if data is not None:
        return data
    else:
        try:
            result = urlfetch.fetch(url,deadline=30) #timeout after 10 sec
            if result.status_code == 200:
                value = process_json(result.content, exchange)
                memcache.add(url, value, 30) #cache for 30 sec
                return value
            else:
                return 'Error'#'Error accessing Vircurex API'
        except runtime.DeadlineExceededError: #raised if the overall request times out
            return 'Error: timeout'
        except runtime.apiproxy_errors.DeadlineExceededError: #raised if an RPC exceeded its deadline (set)
            return 'Error: timeout'
        except urlfetch_errors.DeadlineExceededError: #raised if the URLFetch times out
            return 'Error: timeout'
            
def process_json(str, exchange):
    #should probably add error handling in case bad json is passed
    if exchange == 'vircurex':
        if str == '"Unknown currency"': return 'Error'
        obj = json.loads(str) 
        return obj['value']
    elif exchange == 'mtgox_bid':
        obj = json.loads(str)
        if obj['result'] == 'success':
            return obj['return']['buy']['value']
        else:
            return 'Error: bad MTGox API result'
    elif exchange == 'mtgox_ask':
        obj = json.loads(str)
        if obj['result'] == 'success':
            return obj['return']['sell']['value']
        else:
            return 'Error: bad MTGox API result'
    else:
        return 'Error: invalid exchange'
        
def get_mtgox_value(type,base,alt):
    if type == 'bid':
        exch = 'mtgox_bid'
    elif type == 'ask':
        exch = 'mtgox_ask'
    else:
        return 'Error: Type must be either "bid" or "ask"'
    if base != 'btc': return 'Error: base can only be BTC for mtgox'
    if not any(alt in s for s in ['usd', 'aud', 'cad', 'chf', 'cny', 'dkk',
      'eur', 'gbp', 'hkd', 'jpy', 'nzd', 'pln', 'rub', 'sek', 'sgd', 'thb']):
        return 'Error: invalid destination currency'
    # should figure out a way to do btc as alt and a currency as base
    url = 'http://data.mtgox.com/api/1/btc'+alt+'/ticker'
    value = urlfetch_cache(url,exch)
    return value
    
def get_vircurex_value(type, base, alt):
    # gets json from vircurex about bid/ask prices
    # eg. https://vircurex.com/api/get_highest_bid.json?base=BTC&alt=NMC
    if type == 'bid':
        url = 'https://vircurex.com/api/get_highest_bid.json'
    elif type == 'ask':
        url = 'https://vircurex.com/api/get_lowest_ask.json'
    else:
        return 'Error: Type must be either "bid" or "ask"'
    cur = ['btc', 'dvc', 'ixc', 'ltc', 'nmc', 'ppc', 'trc', 'usd', 'eur']
    if not any(base in s for s in cur): return 'Error: invalid currency'
    if not any(alt in s for s in cur): return 'Error: invalid currency'
    
    url += '?base=' + base + '&alt=' + alt
    value = urlfetch_cache(url,'vircurex')
    return value
    
    #if result.status_code == 200 and result.content != '"Unknown currency"':
    #    obj = json.loads(result.content)
    #    return obj['value']
    #else:
    #    return 'Error'#'Error accessing Vircurex API'
    
def get_bid(exchange, base, alt):
    if exchange == 'vircurex':
        return get_vircurex_value('bid',base,alt)
    elif exchange == 'mtgox':
        return get_mtgox_value('bid',base,alt)
    else:
        return 'Error'
    
class MainHandler(webapp2.RequestHandler):
    def get(self):
        #base = self.request.get('base','dvc')
        #alt = self.request.get('alt','btc')
        #value = get_vircurex_value('bid',base,alt)
        
        #template_values = {
        #    'value': value
        #}
        
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render())#template_values))
        
class ImageHandler(webapp2.RequestHandler):
    def get(self,exchange,amount,base,alt):
        if amount == '': amount = '1'       # default amount is 1
        exchange = exchange.lower()         # make sure everything is lowercase
        base = base.lower()
        if alt == None:
            if base == 'btc': alt = 'usd'   # btc.png just shows btc value in usd
            else: alt = 'btc'               # if no alt specified, default to BTC
        alt = alt.lower()
        bid = get_bid(exchange,base,alt)
        if bid.startswith('Error'): value = bid
        else: value = str(Decimal(amount)*Decimal(bid))
        text_pos = 19                       # 3 px after coin image (all are 16x16)
        
        if value.startswith('Error'):
            text_pos = 0
        elif alt == 'usd':
            # round down to 2 decimal places
            value = '$ '+str(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_DOWN))
            text_pos = 2
        elif alt == 'eur':
            # euro symbol in unicode (only works with truetype fonts)
            value = u'\u20AC '+str(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_DOWN))
            text_pos = 2                    # have to position euro symbol so it doesn't cut off
        elif any(alt in s for s in ['aud', 'cad', 'chf', 'cny', 'dkk',
          'gbp', 'hkd', 'jpy', 'nzd', 'pln', 'rub', 'sek', 'sgd', 'thb']):
          value = alt.upper() + ' ' + value
          text_pos = 2
        
        img = Image.new("RGBA", (1,1))      # just used to calculate the text size, size doesn't matter
        draw = ImageDraw.Draw(img)
        fnt = ImageFont.load('static/font/ncenB12.pil') # for testing locally, can't get truetype to work locally
        #fnt = ImageFont.truetype('static/font/tahoma_bold.ttf', 14, encoding='unic')
        w, h = draw.textsize(value, fnt)    # calculate width font will take up
        
        del img
        img = Image.new("RGBA", (w+text_pos,20))
        draw = ImageDraw.Draw(img)          # set draw to new image
        #text_pos 0 = error
        if text_pos!=0 and any(alt in s for s in ['btc', 'dvc', 'ixc', 'ltc', 'nmc', 'ppc', 'trc']):
            coinimg = Image.open('static/img/'+alt+'.png') 
            img.paste(coinimg, (0,2))       #paste the coin image into the generated image
        
        draw.text((text_pos,1), value, font=fnt, fill='#555555')
        del draw
        
        output = StringIO.StringIO()
        img.save(output, format='png')
        img_to_serve = output.getvalue()
        output.close()
        
        self.response.headers['Content-Type'] = 'image/png'
        self.response.out.write(img_to_serve)

app = webapp2.WSGIApplication([
    ('/', MainHandler),
    ('/([^/]+)/(\d*\.?\d*)([A-Za-z]{3})(?:/([A-Za-z]{3}))?(?:\.png)?', ImageHandler)
], debug=True)
