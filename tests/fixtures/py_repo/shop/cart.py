import json
from . import prices
from billing.invoice import make_invoice
import requests


def total(items):
    return prices.sum_prices(items)
