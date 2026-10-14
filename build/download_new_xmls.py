import requests
import os
import time

# Configurazione
BASE_URL = "https://documenti.camera.it/apps/commonServices/getDocumento.ashx?sezione=assemblea&tipoDoc=formato_xml&tipologia=stenografico&idNumero={:04d}&idLegislatura=19"
OUTPUT_DIR = "data/xml"
START_ID = 588  # Inizia dal successivo all'ultimo citato (587)
MAX_EMPTY_RETRIES = 3 # Quante volte riprovare prima di fermarsi del tutto (opzionale)

def download_xml(doc_id: int) -> bool:
    """
    Scarica un singolo file XML. 
    Ritorna True se il download ha avuto successo, False se il documento non è disponibile.
    """
    url = BASE_URL.format(doc_id)
    filename = f"stenografico_leg19_{doc_id:04d}.xml"
    filepath = os.path.join(OUTPUT_DIR, filename)

    try:
        response = requests.get(url, timeout=30)
        
        # Se il server risponde con successo
        if response.status_code == 200:
            content = response.text
            
            # Verifica se il contenuto indica che il documento non è disponibile
            # Spesso i servizi della Camera restituiscono un messaggio testuale invece di un 404
            if "Documento non disponibile" in content or len(content.strip()) < 100:
                print(f"[{doc_id:04d}] Fine della serie: Documento non disponibile.")
                return False
            
            # Salva il file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[{doc_id:04d}] Scaricato con successo: {filename}")
            return True
        else:
            print(f"[{doc_id:04d}] Errore HTTP {response.status_code}")
            return False

    except Exception as e:
        print(f"[{doc_id:04d}] Errore durante il download: {e}")
        return False

def main():
    # Assicurati che la cartella esista
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Creata directory: {OUTPUT_DIR}")

    current_id = START_ID
    
    print(f"Inizio scraping stenografici a partire dall'ID: {current_id}")
    print("=" * 50)

    while True:
        success = download_xml(current_id)
        
        if not success:
            # Potrebbe esserci un "buco" nella numerazione? 
            # Di solito no per le sedute, ma se vuoi essere sicuro potresti aggiungere un rinvio.
            # Per ora seguiamo la specifica: stop al primo "non disponibile".
            break
            
        current_id += 1
        # Piccolo delay per non sovraccaricare il server
        time.sleep(0.5)

    print("=" * 50)
    print(f"Scraping completato. Ultimo ID elaborato: {current_id - 1}")

if __name__ == "__main__":
    main()
