from bs4 import BeautifulSoup
import requests


def parse():
    URL = 'https://autopapa.ge/ge/usd/search?order=date&page=1'
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36'
    }
    HOST = 'https://autopapa.ge'

    response = requests.get(URL, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')

    items = soup.find_all('div', class_='boxCatalog2')
    comps = []


    for item in items:
        comps.append({
            'title': item.find('a', class_='with_hash2').get_text(strip=True),
            'price': item.find('div', class_='priceCatalog price').get_text(strip=True),
            'link': HOST + item.find('a', class_='with_hash2').get('href'),
            'info': item.find('div', class_='paramCatalog').get_text(strip=True).replace('(AUTOPAPA)', '')
        })

    for comp in comps:
        print(f'{comp["title"]} -> ინფორმაცია: {comp["info"]} -> ფასი: {comp["price"]} -> ლინკი: {comp["link"]}')

parse()