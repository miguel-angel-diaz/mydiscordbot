import os
import hashlib
import pandas as pd
import aiohttp
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

class MkmLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.df = None
        self.last_update = None
        self._loaded = False

        # Expansiones Premodern y sus nombres para búsqueda
        self.premodern_expansions = {
            "fourth edition": 10, "ice age": 11, "chronicles": 12,
            "homelands": 14, "alliances": 15, "mirage": 16,
            "visions": 17, "weatherlight": 18, "tempest": 19,
            "stronghold": 20, "exodus": 21, "fifth edition": 23,
            "urza's saga": 26, "urza's legacy": 27, "urza's destiny": 28,
            "sixth edition": 29, "mercadian masques": 31, "nemesis": 32,
            "prophecy": 33, "invasion": 34, "planeshift": 35,
            "apocalypse": 36, "seventh edition": 37, "odyssey": 38,
            "torment": 39, "judgment": 40, "onslaught": 41,
            "legions": 42, "scourge": 43
        }
        # Mapa inverso para búsqueda por ID
        self.expansion_id_to_name = {v: k for k, v in self.premodern_expansions.items()}

        # Nombres de expansión (en inglés) para búsqueda flexible
        self.expansion_name_to_key = {name: name for name in self.premodern_expansions}

    def get_csv_hash(self, filename: str) -> Optional[str]:
        """Calcula el hash MD5 de un archivo CSV."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            return None
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    async def download_csv(self, session: aiohttp.ClientSession, url: str, filename: str) -> bool:
        """Descarga un CSV desde una URL (requiere autenticación previa)."""
        try:
            # Necesitas pasar las cookies de sesión. Esto es solo un esqueleto.
            # Para que funcione, debes tener las cookies guardadas en un archivo o variable.
            # Por ahora, lanzamos un error si no se proporcionan cookies.
            raise NotImplementedError("La descarga automática requiere cookies de autenticación. Descarga manualmente los CSVs.")
            # Si tuvieras cookies:
            # cookies = {'PHPSESSID': '...'}
            # async with session.get(url, cookies=cookies) as resp:
            #     if resp.status == 200:
            #         with open(self.data_dir / filename, 'wb') as f:
            #             f.write(await resp.read())
            #         return True
            #     return False
        except Exception as e:
            logger.error(f"Error descargando {filename}: {e}")
            return False

    def load_csvs(self) -> bool:
        """Carga los CSVs desde la carpeta data/ y los fusiona."""
        price_path = self.data_dir / "priceguide.csv"
        product_path = self.data_dir / "productcatalogue.csv"

        if not price_path.exists() or not product_path.exists():
            logger.error("CSVs no encontrados. Descárgalos manualmente de Cardmarket.")
            return False

        try:
            # Cargar CSVs con pandas
            price_df = pd.read_csv(price_path, encoding='latin1', delimiter=';')
            product_df = pd.read_csv(product_path, encoding='latin1', delimiter=';')

            # Fusionar por idProduct
            self.df = pd.merge(
                price_df,
                product_df[['idProduct', 'expansionName', 'productName']],
                on='idProduct',
                how='inner'
            )

            # Limpiar nombres para búsquedas
            self.df['expansionName_lower'] = self.df['expansionName'].str.lower()
            self.df['productName_lower'] = self.df['productName'].str.lower()

            self.last_update = datetime.now()
            self._loaded = True
            logger.info(f"CSVs cargados: {len(self.df)} registros")
            return True

        except Exception as e:
            logger.error(f"Error cargando CSVs: {e}")
            return False

    def reload(self):
        """Recarga los CSVs forzadamente."""
        self._loaded = False
        self.load_csvs()

    def get_card_price(self, card_name: str, expansion: Optional[str] = None) -> Optional[Dict]:
        """Busca una carta por nombre y expansión (opcional)."""
        if not self._loaded:
            if not self.load_csvs():
                return None

        mask = self.df['productName_lower'] == card_name.lower()
        if expansion:
            # Buscar por nombre de expansión (insensible a mayúsculas)
            exp_lower = expansion.lower()
            mask &= self.df['expansionName_lower'] == exp_lower

        results = self.df[mask]
        if results.empty:
            # Búsqueda parcial por nombre
            mask = self.df['productName_lower'].str.contains(card_name.lower(), na=False)
            if expansion:
                mask &= self.df['expansionName_lower'] == expansion.lower()
            results = self.df[mask]

        if results.empty:
            return None

        row = results.iloc[0]
        return {
            'name': row['productName'],
            'expansion': row['expansionName'],
            'avg': row.get('priceGuideSell', 0.0),
            'low': row.get('priceGuideLow', 0.0),
            'trend': row.get('priceGuideTrend', 0.0),
            'avg1': row.get('priceGuideAvg1', 0.0),
            'avg7': row.get('priceGuideAvg7', 0.0),
            'avg30': row.get('priceGuideAvg30', 0.0),
        }

    def get_cards_by_expansion(self, expansion_name: str) -> List[Dict]:
        """Devuelve todas las cartas de una expansión."""
        if not self._loaded:
            if not self.load_csvs():
                return []

        mask = self.df['expansionName_lower'] == expansion_name.lower()
        results = self.df[mask]
        cards = []
        for _, row in results.iterrows():
            cards.append({
                'name': row['productName'],
                'expansion': row['expansionName'],
                'avg': row.get('priceGuideSell', 0.0),
                'low': row.get('priceGuideLow', 0.0),
                'trend': row.get('priceGuideTrend', 0.0),
            })
        return cards

    def compare_expansions(self, old_exp_name: str, new_exp_name: str, top_n: int = 10) -> Tuple[Optional[List], Optional[str]]:
        """Compara precios entre dos expansiones."""
        if not self._loaded:
            if not self.load_csvs():
                return None, "Datos no disponibles"

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
            return None, "No hay cartas en común entre las dos expansiones"

        results = []
        for name in common:
            old_price = old_index[name]['avg']
            new_price = new_index[name]['avg']
            if old_price == 0 or new_price == 0:
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

# Instancia global para usar en main.py
mkm_loader = MkmLoader()