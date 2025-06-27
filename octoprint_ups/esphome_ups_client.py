import requests

class EsphomeUPSClient:
    def __init__(self, base_url, entity_power, entity_critical, entity_shutdown, token=None):
        self.base_url = base_url.rstrip('/')
        self.entity_power = entity_power
        self.entity_critical = entity_critical
        self.entity_shutdown = entity_shutdown
        self.token = token

    def _get_headers(self):
        headers = {
            "Content-Type": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_status(self):
        try:
            res_power = requests.get(f"{self.base_url}/api/states/{self.entity_power}", headers=self._get_headers())
            res_critical = requests.get(f"{self.base_url}/api/states/{self.entity_critical}", headers=self._get_headers())
            if res_power.status_code == 200 and res_critical.status_code == 200:
                on_battery = res_power.json()['state'] == 'on'
                critical = res_critical.json()['state'] == 'on'
                return dict(on_battery=on_battery, critical=critical)
            else:
                return None
        except Exception as e:
            return None

    def shutdown(self):
        try:
            payload = {"entity_id": self.entity_shutdown}
            response = requests.post(f"{self.base_url}/api/services/switch/turn_on", json=payload, headers=self._get_headers())
            return response.status_code == 200
        except Exception:
            return False
