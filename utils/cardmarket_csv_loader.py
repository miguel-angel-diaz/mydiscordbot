import pandas as pd
from pathlib import Path
import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

class CardmarketCSVLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.df = None
        self.last_update = None
        self._loaded = False
        
        # Mapeo de expansiones (IDs no necesarios, usamos nombres exactos)
        # Para búsquedas por nombre de expansión
        self.premodern_expansions = {
            "fourth edition": "Fourth Edition",
            "ice age": "Ice Age",
            "chronicles": "Chronicles",
            "homelands": "Homelands",
            "alliances": "Alliances",
            "mirage": "Mirage",
            "visions": "Visions",
            "weatherlight": "Weatherlight",
            "tempest": "Tempest",
            "stronghold": "Stronghold",
            "exodus": "Exodus",
            "fifth edition": "Fifth Edition",
            "urza's saga": "Urza's Saga",
            "urza's legacy": "Urza's Legacy",
            "urza's destiny": "Urza's Destiny",
            "sixth edition": "Sixth Edition",
            "mercadian masques": "Mercadian Masques",
            "nemesis": "Nemesis",
            "prophecy": "Prophecy",
            "invasion": "Invasion",
            "planeshift": "Planeshift",
            "apocalypse": "Apocalypse",
            "seventh edition": "Seventh Edition",
            "odyssey": "Odyssey",
            "torment": "Torment",
            "judgment": "Judgment",
            "onslaught": "Onslaught",
            "legions": "Legions",
            "scourge": "Scourge",
        }
        # Invertir para búsqueda por nombre real -> clave
        self.expansion_name_to_key = {v.lower(): k for k, v in self.premodern_expansions.items()}
        
        # Cargar al instanciar
        self.load_csvs()

    def load_csvs(self) -> bool:
        """Carga los CSVs y los fusiona en un DataFrame."""
        if self._loaded:
            return True
            
        price_path = self.data_dir / "priceguide.csv"
        product_path = self.data_dir / "productcatalogue.csv"

        if not price_path.exists() or not product_path.exists():
            logger.warning(f"CSVs no encontrados. Ejecuta el downloader primero.")
            return False

        try:
            # Cargar precios (delimitador ; y encoding latin1)
            price_df = pd.read_csv(price_path, encoding='latin1', delimiter=';')
            logger.info(f"Precios cargados: {len(price_df)} registros")

            # Cargar catálogo
            product_df = pd.read_csv(product_path, encoding='latin1', delimiter=';')
            logger.info(f"Catálogo cargado: {len(product_df)} registros")

            # Fusionar por ID de producto
            self.df = pd.merge(
                price_df,
                product_df[['idProduct', 'expansionName', 'productName']],
                on='idProduct',
                how='inner'
            )

            self.last_update = datetime.now()
            logger.info(f"Datos fusionados: {len(self.df)} cartas con precio y expansión")
            
            # Limpiar nombres para búsquedas
            self.df['expansionName_lower'] = self.df['expansionName'].str.lower()
            self.df['productName_lower'] = self.df['productName'].str.lower()
            
            self._loaded = True
            return True

        except Exception as e:
            logger.error(f"Error cargando CSVs: {e}")
            return False

    def reload(self) -> bool:
        """Recarga los datos desde los archivos."""
        self._loaded = False
        return self.load_csvs()

    def get_card_price(self, card_name: str, expansion_name: Optional[str] = None) -> Optional[Dict]:
        """Busca una carta por nombre y devuelve su información de precio."""
        if not self._loaded:
            if not self.load_csvs():
                return None

        # Intentar primero búsqueda exacta (insensible a mayúsculas)
        mask = self.df['productName_lower'] == card_name.lower()
        
        if expansion_name:
            # Buscar por nombre de expansión (puede ser el real o el simplificado)
            exp_key = expansion_name.lower()
            # Si es una de las claves simplificadas, obtener el nombre real
            if exp_key in self.premodern_expansions:
                real_exp_name = self.premodern_expansions[exp_key]
                mask &= self.df['expansionName_lower'] == real_exp_name.lower()
            else:
                mask &= self.df['expansionName_lower'] == exp_key

        results = self.df[mask]
        
        # Si no hay resultados, intentar búsqueda parcial
        if results.empty:
            mask = self.df['productName_lower'].str.contains(card_name.lower(), na=False)
            if expansion_name:
                exp_key = expansion_name.lower()
                if exp_key in self.premodern_expansions:
                    real_exp_name = self.premodern_expansions[exp_key]
                    mask &= self.df['expansionName_lower'] == real_exp_name.lower()
                else:
                    mask &= self.df['expansionName_lower'] == exp_key
            results = self.df[mask]

        if results.empty:
            return None

        # Devolver el primer resultado
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
        """Devuelve todas las cartas de una expansión con sus precios."""
        if not self._loaded:
            if not self.load_csvs():
                return []

        exp_key = expansion_name.lower()
        if exp_key in self.premodern_expansions:
            real_exp_name = self.premodern_expansions[exp_key]
            mask = self.df['expansionName_lower'] == real_exp_name.lower()
        else:
            mask = self.df['expansionName_lower'] == exp_key

        results = self.df[mask]
        
        if results.empty:
            return []

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
        """Compara precios entre dos expansiones y devuelve el top N de subidas."""
        if not self._loaded:
            if not self.load_csvs():
                return None, "Datos no disponibles"

        old_cards = self.get_cards_by_expansion(old_exp_name)
        new_cards = self.get_cards_by_expansion(new_exp_name)

        if not old_cards:
            return None, f"No hay cartas en {old_exp_name}"
        if not new_cards:
            return None, f"No hay cartas en {new_exp_name}"

        # Crear índices por nombre
        old_index = {c['name']: c for c in old_cards}
        new_index = {c['name']: c for c in new_cards}

        common_names = set(old_index.keys()) & set(new_index.keys())
        if not common_names:
            return None, "No hay cartas en común"

        results = []
        for name in common_names:
            old_price = old_index[name].get('avg', 0)
            new_price = new_index[name].get('avg', 0)
            if old_price == 0 or new_price == 0:
                continue
            pct_change = ((new_price - old_price) / old_price) * 100
            results.append({
                'name': name,
                'old_price': old_price,
                'new_price': new_price,
                'pct_change': pct_change,
                'abs_change': new_price - old_price
            })

        results.sort(key=lambda x: x['pct_change'], reverse=True)
        return results[:top_n], None