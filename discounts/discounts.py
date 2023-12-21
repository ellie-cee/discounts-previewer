import json
from flask import app
from flask import g
from flask import Response
import sqlite3
from datetime import datetime
from dateutil import parser
import functools
import shopify
import requests
import os
import sys
from gql import Client,gql
from gql.transport.requests import RequestsHTTPTransport


class DiscountHandler:
    def __init__(self,app,site,code) -> None:
        self.site = site
        self.code = code
        self.app = app
        self.site_data = dict(self.db().execute(f"select * from site where shopify_name='{site}' limit 1").fetchone())
        print(self.site_data,file=sys.stderr)
        
        if not self.site_data is None:
            self.client = Client(
                transport=RequestsHTTPTransport(
                    url=f"https://{self.site_data.get('shopify_name')}.myshopify.com/admin/api/2023-04/graphql.json",
                    verify=True,
                    retries=3,
                    headers={"X-Shopify-Access-Token": self.site_data.get("api_secret")}
                ),
                fetch_schema_from_transport=False
            )
            print(f"https://{self.site_data.get('shopify_name')}.myshopify.com/admin/api/2023-04/graphql.json")
    def db(self,file="sites.sqlite"):
        with self.app.app_context():
            handle = getattr(g,"_database",None)
            if handle is None:
                db = g._database = sqlite3.connect(f"./db/{file}")
                db.row_factory = sqlite3.Row
            return db.cursor()
    def retval(self,payload,status=200,ef=None):
        if ef is not None:
            payload["error"] = ef
        return Response(
                json.dumps(payload),
                status=status
            )
    def run(self,request):
        payload = request.get_json()
        if self.site_data is None:
            return self.retval(payload,200,"Site not configured")
        if self.site_data["active"] != 1:
            return self.retval(payload,200,"Site Inactive")
        res = dict(self.code_query(self.code))["codeDiscountNodeByCode"]
        if res is None:
            return self.retval(payload,200,"Invalid Code")
        else:
            res = res["codeDiscount"]
        
        now = datetime.now()
        print(json.dumps(res,indent=2),file=sys.stderr)
        if now<parser.parse(res["startsAt"].split("T")[0]):
            return self.retval(payload,200,f"Code {self.code} has not started yet!")
        if res["endsAt"] is not None:
            if now>parser.parse(res["endsAt"].split("T")[0]):
                return self.retval(payload,200,f"Code {self.code} is expired!")
        if res["status"] != "ACTIVE":
            return self.retval(payload,200,f"Code {self.code} is inactive!")
        
        products = None
        
        if "collections" in res["benefits"]["items"]:
            products = []
            for collection_thing in res["benefits"]["items"]["collections"]["results"]:
                collection = self.collection_query(collection_thing["id"])
                products = products+list(
                    map(
                        lambda x: int(x["id"].split("/")[-1]),
                        collection["collection"]["products"]["results"]
                        )
                    )
        if "products" in res["benefits"]["items"]:
            products = list(
                map(
                    lambda x: int(x["id"].split("/")[-1]),
                    res["benefits"]["items"]["products"]["results"]
                )
            )

        total_items = functools.reduce(lambda a,b: a+b["quantity"],payload["items"],0)
        subtotal = payload["items_subtotal_price"]/100

        if res["minimum"] is not None:
            if "subtotal" in res["minimum"]:
                if subtotal<float(res["minimum"]["subtotal"]["amount"]):
                   return self.retval(payload,200,f'A minimum of {res["minimum"]["subtotal"]["amount"]} is required for code {self.code}')
            elif "quantity" in res["minimum"]:
                if total_items<int(res["minimum"]["quantity"]):
                    return self.retval(payload,200,f'A minimum of {res["minimum"]["quantity"]} is required for code {self.code}')


        if res["discountClass"] == "PRODUCT":
            one_per_order_applied = False
            for item in payload["items"]:
                print(item["product_id"],products,file=sys.stderr)
                apply_discount = True
                if products is None or item["product_id"] in products:
                    if not res["benefits"]["oneTimeValid"] and not "selling_plan_allocation" in item:
                        apply_discount = False
                    if not res["benefits"]["subscriptionValid"] and "selling_plan_allocation" in item:
                        apply_discount = False
                else:
                    apply_discount = False
                    
                if apply_discount:
                    print("applying discounr",file=sys.stderr)
                    if "percentage" in res["benefits"]["value"]:
                        new_price = int(
                            ((item["discounted_price"]/100)*(1-res["benefits"]["value"]["percentage"])*100)
                        )
                        item["discounted_price"] = new_price
                        item["discounts"].append({"title":res["title"]})
                        item["line_price"] = new_price*item["quantity"]
                        item["total_discount"] = item["total_discount"]+(item["original_line_price"]-item["line_price"])
                    elif "amount" in res["benefits"]["value"]:
                        new_price = int(
                            ((item["discounted_price"]/100)-float(res["benefits"]["value"]["amount"]["amount"]))*100
                        )
                        apply_new_price = False
                        if not res["benefits"]["value"]["appliesOnEachItem"] and not one_per_order_applied:
                            apply_new_price = True
                        elif res["benefits"]["value"]["appliesOnEachItem"]:
                            apply_new_price = True
                        if apply_new_price:
                            item["discounted_price"] = new_price
                            item["discounts"].append({"title":res["title"]})
                            item["line_price"] = new_price*item["quantity"]
                            item["total_discount"] = item["total_discount"]+(item["original_line_price"]-item["line_price"])
                            one_per_order_applied = True
                    payload["items_subtotal_price"] = functools.reduce(
                        lambda a,b: a+b["line_price"],
                        payload["items"],
                        0
                    )
                
                
        print(total_items,subtotal,file=sys.stderr)
        
        return Response(
            json.dumps(payload),
            status=200
        )
    


        
    def collection_query(self,gid):
        return self.client.execute(gql("""
            query getCollection($id: ID!) {
                collection(id: $id) {
                   products(first:250) {
                    results: nodes {
                        id
                        handle
                    }                    
                   }
                }
            }
            """),
            variable_values={"id":gid}
        )
    
    def code_query(self,code):
        query=gql("""
        query codeDiscountNodeByCode($code: String!) {
        codeDiscountNodeByCode(code: $code) {
            codeDiscount {
            __typename
            ... on DiscountCodeBasic {
                title
                codeCount
                shortSummary
                benefits: customerGets {
                oneTimeValid: appliesOnOneTimePurchase
                subscriptionValid: appliesOnSubscription
                value {
                    ... on DiscountAmount {
                        amount {
                            amount
                        }
                        appliesOnEachItem
                    }
                    ... on DiscountPercentage {
                        percentage
                    }
                }
                items {
                    ... on DiscountProducts {
                        products: products(first:100) {
                            results: nodes {
                                id
                                handle
                            }
                        }
                    }
                    ... on DiscountCollections {
                        collections: collections(first:100) {
                            results: nodes {
                                id
                                handle
                            }
                        }
                    }
                }
                }
                discountClass
                startsAt
                endsAt
                status
                minimum: minimumRequirement {
                ... on DiscountMinimumQuantity {
                    quantity: greaterThanOrEqualToQuantity
                }
                ... on DiscountMinimumSubtotal {
                    subtotal: greaterThanOrEqualToSubtotal {
                        amount
                    }
                }
                }
            }
            }
            id
        }
        }
        """)
        return self.client.execute(
            query,
            variable_values={"code":code}
        )


        
