from flask import Flask
from flask_cors import CORS
from flask import Response
from flask import request
from flask import g
from flask_caching import Cache
import sqlite3
from discounts.discounts import DiscountHandler
import os
import json



app = Flask(__name__)

def db(app,file="sites.sqlite"):
    with app.app_context():
        handle = getattr(g,"_database",None)
        if handle is None:
            print(f"{os.path.join(app.instance_path,'db',file)}")
            db = g._database = sqlite3.connect(f"./db/{file}")
        return db
def close_connection(exception=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
CORS(
    app,
    resources=r"/*",
    origins=list(map(lambda x:x[0],db(app,"sites.sqlite").cursor().execute("select url from site where active=1").fetchall()))
)


@app.route("/")
def helloWorld():
  return "jfod;w fpn9y9 nr0qny"
@app.route("/cors")
def cors():
    return json.dumps(list(map(lambda x:x[0],db(app,"sites.sqlite").cursor().execute("select url from site where active=1").fetchall())),indent=2)

@app.route("/code/<site>/<code>",methods=["POST","GET"])
def getcode(site,code):
    return DiscountHandler(app,site,code).run(request)
    