# utils/mkm_json_loader.py
import aiohttp
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

class MkmJsonLoader:
    def __init__(self):
        self.products = None
        self.prices = None
        self.merged = None
        self.last_update = None
        self._loaded = False
        self._loading = False
        self._cache_duration = timedelta(hours=24)

        # Expansiones Premodern (mapeo nombre en minúsculas -> ID)
        self.premodern_expansions = {
            "fourth edition": 10,
            "ice age": 11,
            "chronicles": 12,
            "homelands": 14,
            "alliances": 15,
            "mirage": 16,
            "visions": 17,
            "weatherlight": 18,
            "tempest": 19,
            "stronghold": 20,
            "exodus": 21,
            "fifth edition": 23,
            "urza's saga": 26,
            "urza's legacy": 27,
            "urza's destiny": 28,
            "sixth edition": 29,
            "mercadian masques": 31,
            "nemesis": 32,
            "prophecy": 33,
            "invasion": 34,
            "planeshift": 35,
            "apocalypse": 36,
            "seventh edition": 37,
            "odyssey": 38,
            "torment": 39,
            "judgment": 40,
            "onslaught": 41,
            "legions": 42,
            "scourge": 43
        }
        # Mapeo inverso: ID -> nombre (con capitalización correcta)
        self.expansion_id_to_name = {
            v: ' '.join(word.capitalize() for word in k.split())
            for k, v in self.premodern_expansions.items()
        }
        # Lista de nombres para autocompletar en el wizard
        self.expansion_names = list(self.expansion_id_to_name.values())

        # URLs públicas de los JSON
        self.product_url = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
        self.price_url = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"

    async def _download_json(self, session: aiohttp.ClientSession, url: str) -> Optional[Dict]:
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status != 200:
                    print(f"Error descargando {url}: {resp.status}")
                    return None
                return await resp.json()
        except Exception as e:
            print(f"Excepción descargando {url}: {e}")
            return None

    async def load_data(self, force: bool = False) -> bool:
        if self._loaded and not force:
            if self.last_update and datetime.now() - self.last_update < self._cache_duration:
                return True

        if self._loading:
            while self._loading:
                await asyncio.sleep(0.5)
            return self._loaded

        self._loading = True
        try:
            async with aiohttp.ClientSession() as session:
                print("📥 Descargando catálogo de productos...")
                products_data = await self._download_json(session, self.product_url)
                if not products_data:
                    self._loading = False
                    return False

                print("📥 Descargando guía de precios...")
                prices_data = await self._download_json(session, self.price_url)
                if not prices_data:
                    self._loading = False
                    return False

            self.products = products_data.get('products', [])
            product_index = {p['idProduct']: p for p in self.products}
            print(f"✅ Productos cargados: {len(self.products)}")

            self.prices = prices_data.get('priceGuides', [])
            print(f"✅ Precios cargados: {len(self.prices)}")

            # Fusionar productos y precios
            self.merged = []
            for price in self.prices:
                product = product_index.get(price['idProduct'])
                if product:
                    exp_id = product.get('idExpansion')
                    # Obtener nombre de expansión del mapeo (si existe)
                    exp_name = self.expansion_id_to_name.get(exp_id, 'Unknown')

                    self.merged.append({
                        'idProduct': price['idProduct'],
                        'name': product.get('name', 'Unknown'),
                        'expansion_id': exp_id,
                        'expansion_name': exp_name,
                        'avg': price.get('avg'),
                        'low': price.get('low'),
                        'trend': price.get('trend'),
                        'avg1': price.get('avg1'),
                        'avg7': price.get('avg7'),
                        'avg30': price.get('avg30'),
                        'avg_foil': price.get('avg-foil'),
                        'low_foil': price.get('low-foil'),
                        'trend_foil': price.get('trend-foil'),
                    })

            self.last_update = datetime.now()
            self._loaded = True
            print(f"✅ Datos fusionados: {len(self.merged)} cartas con precio")
            return True

        except Exception as e:
            print(f"Error cargando datos: {e}")
            self._loaded = False
            return False
        finally:
            self._loading = False

    def find_card_with_expansion(self, card_name: str, expansion_name: str) -> Optional[Dict]:
        """Busca una carta con nombre y expansión específica."""
        if not self._loaded:
            return None

        card_lower = card_name.lower()
        exp_lower = expansion_name.lower()

        for item in self.merged:
            if item['name'].lower() == card_lower and item['expansion_name'].lower() == exp_lower:
                return item

        # Búsqueda parcial
        for item in self.merged:
            if card_lower in item['name'].lower() and exp_lower in item['expansion_name'].lower():
                return item
        return None

    def get_card_price(self, card_name: str, expansion: Optional[str] = None, first_edition: bool = False) -> Optional[Dict]:
        if not self._loaded:
            return None

        # Si hay expansión, búsqueda específica
        if expansion:
            result = self.find_card_with_expansion(card_name, expansion)
            if result:
                return result

        # Búsqueda general
        matches = []
        for item in self.merged:
            if item['name'].lower() == card_name.lower():
                matches.append(item)

        if not matches:
            for item in self.merged:
                if card_name.lower() in item['name'].lower():
                    matches.append(item)

        if not matches:
            return None

        if first_edition:
            matches.sort(key=lambda x: x.get('expansion_id', 9999))
        else:
            matches.sort(key=lambda x: x.get('avg') or 999999)

        return matches[0]

    def get_all_versions(self, card_name: str, expansion: Optional[str] = None) -> List[Dict]:
        """Devuelve todas las versiones (ediciones) de una carta, ordenadas por expansion_id."""
        if not self._loaded:
            return []

        matches = []
        for item in self.merged:
            if item['name'].lower() == card_name.lower():
                matches.append(item)

        if not matches:
            for item in self.merged:
                if card_name.lower() in item['name'].lower():
                    matches.append(item)

        if expansion:
            exp_lower = expansion.lower()
            matches = [m for m in matches if m['expansion_name'].lower() == exp_lower]

        # Ordenar por ID de expansión (más antiguo primero)
        matches.sort(key=lambda x: x.get('expansion_id', 9999))
        return matches

    def get_cards_by_expansion(self, expansion_name: str) -> List[Dict]:
        if not self._loaded:
            return []
        exp_lower = expansion_name.lower()
        return [item for item in self.merged if item['expansion_name'].lower() == exp_lower]

    def compare_expansions(self, old_exp_name: str, new_exp_name: str, top_n: int = 10) -> Tuple[Optional[List], Optional[str]]:
        if not self._loaded:
            return None, "Datos no disponibles. Intenta en unos segundos."

        old_cards = self.get_cards_by_expansion(old_exp_name)
        new_cards = self.get_cards_by_expansion(new_exp_name)

        if not old_cards:
            return None, f"No hay cartas en {old_exp_name}"
        if not new_cards:
            return None, f"No hay cartas en {new_exp_name}"

        old_index = {c['name']: c for c in old_cards}
        new_index = {c['name']: c for c in new_cards}

        common = set(old_index.keys()) & set(new_index.keys())
        if not common:
            return None, "No hay cartas en común"

        results = []
        for name in common:
            old_price = old_index[name].get('avg')
            new_price = new_index[name].get('avg')
            if old_price is None or new_price is None or old_price == 0:
                continue
            pct = ((new_price - old_price) / old_price) * 100
            results.append({
                'name': name,
                'old_price': old_price,
                'new_price': new_price,
                'pct_change': pct,
                'abs_change': new_price - old_price
            })

        results.sort(key=lambda x: x['pct_change'], reverse=True)
        return results[:top_n], None

    async def get_card_image_url(self, card_name: str, expansion: Optional[str] = None) -> Optional[str]:
        """Obtiene la URL de la imagen de Scryfall para una carta."""
        search_name = card_name.replace("'", "").strip()
        if expansion:
            search_name = f"{search_name} {expansion}"

        url = f"https://api.scryfall.com/cards/named?fuzzy={search_name}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if 'image_uris' in data:
                            return data['image_uris'].get('normal')
                        elif 'card_faces' in data and len(data['card_faces']) > 0:
                            return data['card_faces'][0].get('image_uris', {}).get('normal')
                    else:
                        print(f"Error Scryfall para {search_name}: {resp.status}")
                        return None
        except Exception as e:
            print(f"Excepción Scryfall para {search_name}: {e}")
            return None
        return None

# Instancia global para usar en toda la app
mkm_loader = MkmJsonLoader()