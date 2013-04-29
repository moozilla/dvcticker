import webapp2
from google.appengine.api import urlfetch
import json
from PIL import Image, ImageDraw, ImageFont
from google.appengine.api import memcache
import StringIO
import jinja2
import os
from decimal import * #used fixed point math for better accuracy

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

def urlfetch_cache(url):
    # fetches a url, but using memcache to not hammer the exchanges server
    data = memcache.get(url)
    if data is not None:
        return data
    else:
        result = urlfetch.fetch(url)
        if result.status_code == 200 and result.content != '"Unknown currency"':
            obj = json.loads(result.content) #should probably add error handling in case bad json is passed
            value = obj['value']
            memcache.add(url, value, 15) #cache for 15 sec
            return value
        else:
            return 'Error'#'Error accessing Vircurex API'
    
def get_vircurex_json(type, base, alt):
    # gets json from vircurex about bid/ask prices
    # eg. https://vircurex.com/api/get_highest_bid.json?base=BTC&alt=NMC
    if type == 'bid':
        url = 'https://vircurex.com/api/get_highest_bid.json'
    elif type == 'ask':
        url = 'https://vircurex.com/api/get_lowest_ask.json'
    else:
        return 'Type must be either "bid" or "ask"'
    url += '?base=' + base + '&alt=' + alt
    value = urlfetch_cache(url)
    return value
    
    #if result.status_code == 200 and result.content != '"Unknown currency"':
    #    obj = json.loads(result.content)
    #    return obj['value']
    #else:
    #    return 'Error'#'Error accessing Vircurex API'

class MainHandler(webapp2.RequestHandler):
    def get(self):
        base = self.request.get('base','dvc')
        alt = self.request.get('alt','btc')
        value = get_vircurex_json('bid',base,alt)
        
        template_values = {
            'value': value
        }
        
        template = JINJA_ENVIRONMENT.get_template('index.html')
        self.response.write(template.render(template_values))
        
class ImageHandler(webapp2.RequestHandler):
    def get(self,exchange,amount,base,alt):
        if amount == '': amount = '1'   # default amount is 1
        if alt == None:
            if base == 'btc': alt = 'usd'   # btc.png just shows btc value in usd
            else: alt = 'btc'               # if no alt specified, default to BTC
        value = str(Decimal(amount)*Decimal(get_vircurex_json('bid',base,alt)))
        width = 120 # should be determined programatically
        text_pos = 19   # 3 px after coin image (all are 16x16)
        
        if alt == 'usd':
            # round down to 2 decimal places
            value = '$ '+str(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_DOWN))
            text_pos = 2
        if alt == 'eur':
            # euro symbol in unicode (only works with truetype fonts)
            value = u'\u20AC '+str(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_DOWN))
            text_pos = 2                # have to position euro symbol so it doesn't cut off
        if alt == 'dvc':
            width = 160     # bigger width for dvc because it tends to have more digits
        if value == 'Error':
            text_pos = 0
        
        img = Image.new("RGBA", (width,20))
        if any(alt in s for s in ['btc', 'dvc', 'ixc', 'ltc', 'nmc', 'ppc', 'trc']):
            coinimg = Image.open('static/img/'+alt+'.png') 
            img.paste(coinimg, (0,2)) #paste the coin image into the generated image
            
        draw = ImageDraw.Draw(img)
        #fnt = ImageFont.load('static/font/ncenB12.pil') # for testing locally, can't get truetype to work locally
        fnt = ImageFont.truetype('static/font/tahoma_bold.ttf', 14, encoding='unic')
        draw.text((text_pos,1), value, font=fnt, fill='#333333')
        del draw
        
        output = StringIO.StringIO()
        img.save(output, format='png')
        img_to_serve = output.getvalue()
        output.close()
        
        self.response.headers['Content-Type'] = 'image/png'
        self.response.out.write(img_to_serve)

app = webapp2.WSGIApplication([
    ('/', MainHandler),
    ('/([^/]+)/(\d*\.?\d*)([a-z]{3})(?:/([a-z]{3}))?(?:\.png)?', ImageHandler)
], debug=True)
