import html
import json
import logging
import os
import random
import time
from datetime import datetime

import pandas as pd
import parsel
import requests

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


class bing_maps:
    def __init__(self):
        root = os.path.dirname(os.path.abspath(__file__))
        self.output = os.path.join(root, 'output')
        os.makedirs(self.output, exist_ok=True)

        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
        self.headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9,bn;q=0.8,de;q=0.7',
            'ect': '4g',
            'priority': 'u=1, i',
            'user-agent': self.user_agent
        }

        self.column_mapping = {
            "company_name": "Business name",
            "phone": "Business phone number",
            "full_address": "Complete address",
            "website": "Website",
            "city": "City",
            "state": "State",
            "map_url": "Source URL"
        }

        # Safely load proxies if the file exists
        proxy_file = os.path.join(root, "proxies.txt")
        if os.path.exists(proxy_file):
            with open(proxy_file, encoding="utf-8") as f:
                self.all_working_proxies = [
                    i.strip() for i in f.read().splitlines()
                    if i.strip() and i.strip().startswith("http")
                ]
        else:
            self.all_working_proxies = []
            logging.warning("proxies.txt not found. Proceeding without proxies.")

        # temp input
        # query = "cafe in barishal, bangladesh"
        query = input("Please enter search query: ")
        self.queries = [query]
        self.main_records = []
        self.start_process()

    def start_process(self):
        for ind, query in enumerate(self.queries, start=1):
            logging.info(f"Currently running {ind}/{len(self.queries)} || Query: {query}")
            records = self.search_places(query)
            self.main_records.extend(records)

        if self.main_records:
            main_df = pd.DataFrame(self.main_records)
            main_df.rename(columns=self.column_mapping, inplace=True)

            final_df = main_df[list(self.column_mapping.values())].copy()
            final_df['Collection date'] = datetime.now().date()

            output_path = os.path.join(self.output, 'bing_maps_results.xlsx')
            final_df.to_excel(output_path, index=False)
            logging.info(f"Saved {len(final_df)} records to {output_path}")
        else:
            logging.warning("No records collected.")

    def search_places(self, query: str, retry=10):
        url = "https://www.bing.com/maps/overlaybfpr"
        params = {"q": query, "filters": 'MapCardType:"details" direction_partner:"maps"'}
        headers = self.headers.copy()
        main_records = []

        for i in range(retry):
            proxy_dict = None
            if self.all_working_proxies:
                proxy = random.choice(self.all_working_proxies)
                proxy_dict = {"https": proxy, "http": proxy}

            try:
                response = requests.get(url, headers=headers, params=params, proxies=proxy_dict, timeout=10)
                if response.status_code == 200:
                    main_records += self.place_parser(response.text)
                    break
                else:
                    logging.warning(f"Retrying - {i + 1}. Status code: {response.status_code}")
            except Exception:
                logging.error(f"Retrying - {i + 1}. Error during request with proxy {proxy_dict}", exc_info=True)

        return main_records

    def place_parser(self, page_source):
        page_dom = parsel.Selector(page_source)
        new_records = []
        listings = page_dom.xpath('//a[contains(@class, "listings-item")]/@data-entity').getall()
        logging.info(f"Found {len(listings)} listings")
        for data in listings:
            try:
                data_dict = json.loads(html.unescape(data))

                # Extract coordinates
                long_lat = data_dict.get('routablePoint', {})
                lat = long_lat.get('latitude')
                lon = long_lat.get('longitude')

                # Extract basic entity details
                main_info = data_dict.get('entity', {})
                company_name = main_info.get('title')
                bing_address = main_info.get('address')
                phone = main_info.get('phone')
                website = main_info.get('website')
                data_id = data_dict.get('id')
                source_url = f"https://www.bing.com/maps/search?ss=id.{data_id}"

                # Reverse geocode via Nominatim if lat/lon exist
                full_address = bing_address
                city = None
                state = None

                if lat is not None and lon is not None:
                    address_info = self.reverse_geocoding_nominatim(lat, lon)
                    if address_info:
                        full_address = address_info.get('display_name', bing_address)
                        addr_details = address_info.get('address', {})

                        # Nominatim uses different keys depending on locality size
                        city = (
                                addr_details.get('city')
                                or addr_details.get('town')
                                or addr_details.get('village')
                                or addr_details.get('municipality')
                                or addr_details.get('county')
                        )
                        state = (
                                addr_details.get('state')
                                or addr_details.get('division')
                                or addr_details.get('region')
                        )

                record = {
                    "company_name": company_name,
                    "phone": phone,
                    "full_address": full_address,
                    "website": website,
                    "city": city,
                    "state": state,
                    "map_url": source_url,
                    "latitude": lat,
                    "longitude": lon
                }
                new_records.append(record)
                logging.info(f"Parsed: {company_name} | City: {city} | State: {state}")

            except Exception:
                logging.error("Error parsing listing item", exc_info=True)

        return new_records

    def reverse_geocoding_nominatim(self, latitude, longitude):
        url = "https://nominatim.openstreetmap.org/reverse.php"
        params = {
            "lat": latitude,
            "lon": longitude,
            "format": "jsonv2",
            "accept-language": "en"
        }

        headers = {
            'referer': f'https://nominatim.openstreetmap.org/ui/reverse.html?lat={latitude}&lon={longitude}',
            'user-agent': self.user_agent,
            'Accept': 'application/json'
        }

        for i in range(5):
            try:
                proxy_dict = None
                if self.all_working_proxies:
                    proxy = random.choice(self.all_working_proxies)
                    proxy_dict = {"https": proxy, "http": proxy}
                res = requests.get(url=url, params=params, headers=headers, proxies=proxy_dict, timeout=30)
                if res.status_code == 200:
                    return res.json()
                elif res.status_code == 429:
                    logging.warning(f"Nominatim rate limit hit. Sleeping 5s... (Attempt {i + 1})")
                    time.sleep(5)
                else:
                    logging.error(f"Nominatim bad status {res.status_code} - Retrying ({i + 1}/5)")
            except Exception:
                logging.error(f"Error calling Nominatim - Retrying ({i + 1}/5)", exc_info=True)

        return None


if __name__ == '__main__':
    bing_maps()
