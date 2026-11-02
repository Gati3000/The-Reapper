from flask import Flask
app = Flask(__name__, template_folder='Templates', static_folder='Static', static_url_path='/static')
from . import Routes
