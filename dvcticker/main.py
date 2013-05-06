#todo: raise exceptions, then catch them to generate error images

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
    
#imgFont = ImageFont.load('static/font/ncenB12.pil') # for testing locally, can't get truetype to work locally
imgFont = ImageFont.truetype('static/font/tahoma_bold.ttf', 14, encoding='unic')

def urlfetch_cache(url,exchange):
    # fetches a url, but using memcache to not hammer the exchanges server
    data = memcache.get(url)
    if data is not None:
        return process_json(data, exchange)
    else:
        try:
            result = urlfetch.fetch(url,deadline=30) #timeout after 30 sec
            if result.status_code == 200:
                value = process_json(result.content, exchange)
                memcache.add(url, result.content, 30) #cache for 30 sec
                memcache.add('longcache'+url, result.content, 3000) #also cache for 5min in case of timeouts
                return value
            else:
                return 'Error: '+exchange+' status code '+str(result.status_code) #'Error accessing Vircurex API'
        except runtime.DeadlineExceededError: #raised if the overall request times out
            data = memcache.get('longcache'+url)
            if data is not None: return process_json(data, exchange)
            else: return 'Error: '+exchange+' timeout'
        except runtime.apiproxy_errors.DeadlineExceededError: #raised if an RPC exceeded its deadline (set)
            data = memcache.get('longcache'+url)
            if data is not None: return process_json(data, exchange)
            else: return 'Error: '+exchange+' timeout'
        except urlfetch_errors.DeadlineExceededError: #raised if the URLFetch times out
            data = memcache.get('longcache'+url)
            if data is not None: return process_json(data, exchange)
            else: return 'Error: '+exchange+' timeout'
        except urlfetch.Error: #catch DownloadError
            data = memcache.get('longcache'+url)
            if data is not None: return process_json(data, exchange)
            else: return 'Error: '+exchange+' timeout'
            
def process_json(txt, exchange):
    #should probably add error handling in case bad json is passed
    if exchange == 'vircurex':
        if txt == '"Unknown currency"': return 'Error: bad Vircurex API result'
        obj = json.loads(txt) 
        return obj['value']
    elif exchange == 'mtgox_bid':
        obj = json.loads(txt)
        if obj['result'] == 'success':
            return obj['return']['buy']['value']
        else:
            return 'Error: bad MTGox API result'
    elif exchange == 'mtgox_ask':
        obj = json.loads(txt)
        if obj['result'] == 'success':
            return obj['return']['sell']['value']
        else:
            return 'Error: bad MTGox API result'
    elif exchange == 'btce_bid':
        obj = json.loads(txt)
        if not any('error' in s for s in obj):
            return str(obj['ticker']['buy'])
        else:
            return 'Error: bad BTC-E API result'
    elif exchange == 'btce_ask':
        obj = json.loads(txt)
        if not any('error' in s for s in obj):
            return str(obj['ticker']['sell'])
        else:
            return 'Error: bad BTC-E API result'
    elif exchange == 'campbx_bid':
        obj = json.loads(txt)
        # need to check for error
        return obj['Best Bid']
    elif exchange == 'campbx_ask':
        obj = json.loads(txt)
        # need to check for error
        return obj['Best Ask']
    else:
        return 'Error: invalid exchange'
        
def get_campbx_value(base,alt,amount):
    url = 'http://campbx.com/api/xticker.php'
    reverse = False
    if base == 'btc':
        if alt != 'usd': return 'Error: only BTC/USD valid on CampBX'
        exch = 'campbx_bid'
    elif base == 'usd':
        if alt != 'btc': return 'Error: only BTC/USD valid on CampBX'
        exch = 'campbx_ask'
        reverse = True
    else:
        return 'Error: only BTC/USD valid on CampBX'
    
    value = urlfetch_cache(url,exch)
    if value.startswith('Error'): return value
    
    if reverse: return str((Decimal(amount) / Decimal(value)).quantize(Decimal('.00000001'), rounding=ROUND_DOWN)) # need to round to a certain number
    else: return str(Decimal(amount) * Decimal(value))
        
def get_mtgox_value(base,alt,amount):
    cur = ['usd', 'aud', 'cad', 'chf', 'cny', 'dkk',
      'eur', 'gbp', 'hkd', 'jpy', 'nzd', 'pln', 'rub', 'sek', 'sgd', 'thb']
    reverse = False # true if going from cur-> btc
    if base == 'btc': 
        if not any(alt in s for s in cur):
            return 'Error: invalid destination currency'
        url = 'http://data.mtgox.com/api/1/btc'+alt+'/ticker'
        exch = 'mtgox_bid'
    elif any(base in s for s in cur):
        if alt != 'btc':
            return 'Error: destination currency must be BTC'
        url = 'http://data.mtgox.com/api/1/btc'+base+'/ticker' #mtgox api always has btc first
        exch = 'mtgox_ask'
        reverse = True
    else:
        return 'Error: invalid base currency'
    value = urlfetch_cache(url,exch)
    if value.startswith('Error'): return value
    
    if reverse: return str((Decimal(amount) / Decimal(value)).quantize(Decimal('.00000001'), rounding=ROUND_DOWN)) # need to round to a certain number
    else: return str(Decimal(amount) * Decimal(value))
    
def get_btce_value(base,alt,amount):
    # in BTC-e currencies must be traded in pairs, we also support going in reverse (buying)
    cur_fwd = {'btc':['usd','rur','eur'], 'ltc':['btc','usd','rur'], 'nmc':['btc'], 'usd':['rur'], 'eur':['usd'], 'nvc':['btc'], 'trc':['btc'], 'ppc':['btc'], 'ftc':['btc']}
    cur_rev = {'btc':['ltc','nmc','nvc','trc','ppc','ftc'], 'usd':['btc','ltc'], 'rur':['btc','usd'], 'eur':['btc']}
    reverse = False # if going from cur-> btc
    if any(base in s for s in cur_fwd) and any(alt in s for s in cur_fwd[base]): 
        #if not any(alt in s for s in cur_fwd[base]):
            #return 'Error: invalid destination currency' # can't return here because some can be base or alt
        url = 'https://btc-e.com/api/2/'+base+'_'+alt+'/ticker' #https://btc-e.com/api/2/nmc_btc/ticker
        exch = 'btce_bid'
    else:
        if any(base in s for s in cur_rev):
            if not any(alt in s for s in cur_rev[base]):
                return 'Error: invalid currency pair'
            url = 'https://btc-e.com/api/2/'+alt+'_'+base+'/ticker'
            exch = 'btce_ask'
            reverse = True
        else:
            return 'Error: invalid currency pair'
    value = urlfetch_cache(url,exch)
    if value.startswith('Error'): return value
    
    if reverse: return str((Decimal(amount) / Decimal(value)).quantize(Decimal('.00000001'), rounding=ROUND_DOWN)) # need to round to a certain number
    else: return str(Decimal(amount) * Decimal(value))
    
def get_vircurex_value(type, base, alt, amount):
    # gets json from vircurex about bid/ask prices
    # eg. https://vircurex.com/api/get_highest_bid.json?base=BTC&alt=NMC
    if type == 'bid':
        url = 'https://vircurex.com/api/get_highest_bid.json'
    elif type == 'ask':
        url = 'https://vircurex.com/api/get_lowest_ask.json'
    else:
        return 'Error: Type must be either "bid" or "ask"'
    cur = ['btc', 'dvc', 'ixc', 'ltc', 'nmc', 'ppc', 'trc', 'usd', 'eur', 'ftc', 'frc']
    if not any(base in s for s in cur): return 'Error: invalid currency'
    if not any(alt in s for s in cur): return 'Error: invalid currency'
    
    url += '?base=' + base + '&alt=' + alt
    value = urlfetch_cache(url,'vircurex')
    if value.startswith('Error'): return value
    return str(Decimal(amount)*Decimal(value)) # return amount * value
    
def get_bid(exchange, amount, base, alt):
    if exchange == 'vircurex':
        return get_vircurex_value('bid',base,alt,amount)
    elif exchange == 'mtgox':
        return get_mtgox_value(base,alt,amount)
    elif exchange == 'btc-e':
        return get_btce_value(base,alt,amount)
    elif exchange == 'campbx':
        return get_campbx_value(base,alt,amount)
    else:
        return 'Error: bad exchange'
    
def get_text_width(str):
    img = Image.new("RGBA", (1,1))      # just used to calculate the text size, size doesn't matter
    draw = ImageDraw.Draw(img)
    w, h = draw.textsize(str, imgFont)    # calculate width font will take up
    return w
        
# returns text, with optional coin icon, in string encoded form so it can be written to HTTP response
def make_img(str, text_pos, coinimg=None):
        img = Image.new("RGBA", (get_text_width(str) + text_pos, 20))
        draw = ImageDraw.Draw(img)          # set draw to new image
        
        if coinimg != None:
            img.paste(coinimg, (0,2))       #paste the coin image into the generated image
        
        draw.text((text_pos,1), str, font=imgFont, fill='#555555')
        
        output = StringIO.StringIO()
        img.save(output, format='png')
        img_to_serve = output.getvalue()
        output.close()    
        return img_to_serve
    
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
        value = get_bid(exchange,amount,base,alt)
        #if bid.startswith('Error'): value = bid
        #else: value = str(Decimal(amount)*Decimal(bid))
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
          'gbp', 'hkd', 'jpy', 'nzd', 'pln', 'rub', 'sek', 'sgd', 'thb', 'rur', 'nvc']):
          value = alt.upper() + ' ' + value
          text_pos = 2
        
        #text_pos 0 = error
        if text_pos!=0 and any(alt in s for s in ['btc', 'dvc', 'ixc', 'ltc', 'nmc', 'ppc', 'trc', 'ftc','frc']):
            coinimg = Image.open('static/img/'+alt+'.png') 
        else: coinimg = None    
            
        img_to_serve = make_img(value, text_pos, coinimg)
        
        self.response.headers['Content-Type'] = 'image/png'
        self.response.out.write(img_to_serve)
        
class ErrorHandler(webapp2.RequestHandler):
    def get(self):
        img_to_serve = make_img('Error: Malformed URL', 0)
        
        self.response.headers['Content-Type'] = 'image/png'
        self.response.out.write(img_to_serve)
        
app = webapp2.WSGIApplication([
    ('/', MainHandler),
    ('/([^/]+)/(\d*\.?\d*)([A-Za-z]+)(?:/([A-Za-z]+))?(?:\.png)?', ImageHandler),
    ('/.*', ErrorHandler)
], debug=True)
