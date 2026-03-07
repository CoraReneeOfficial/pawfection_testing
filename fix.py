import requests

def test_endpoint():
    res = requests.get('http://127.0.0.1:5000/api/appointments/search?q=test')
    print(res.status_code)
    print(res.text)

if __name__ == "__main__":
    test_endpoint()
