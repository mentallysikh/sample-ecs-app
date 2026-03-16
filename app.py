from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "CI/CD UPDATE - TEST SUCCESSFUL! -- second try --"

app.run(host="0.0.0.0", port=5000)
