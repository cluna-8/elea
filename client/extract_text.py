#!/usr/bin/env python3
import sys
import os
import unicodedata

def extract_file_text(filepath):
    norm_path = unicodedata.normalize('NFC', filepath)
    if not os.path.exists(norm_path):
        dirname = os.path.dirname(filepath)
        target_base = os.path.basename(filepath)
        found = False
        if os.path.exists(dirname):
            for f in os.listdir(dirname):
                if unicodedata.normalize('NFC', f) == unicodedata.normalize('NFC', target_base):
                    norm_path = os.path.join(dirname, f)
                    found = True
                    break
        if not found:
            return f"Archivo {os.path.basename(filepath)} no encontrado."

    ext = os.path.splitext(norm_path)[1].lower()
    
    try:
        if ext == '.docx':
            import docx
            doc = docx.Document(norm_path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        elif ext == '.txt' or ext == '.csv' or ext == '.json' or ext == '.md':
            with open(norm_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == '.pdf':
            # Sin esto caía al 'else' de abajo: leía los bytes binarios del PDF como si
            # fueran UTF-8 (garabatos), se "enmascaraba" texto sin sentido y el RAG quedaba
            # sin contenido real — mismo tipo de bug real que el de .xlsx (31-ago).
            from pypdf import PdfReader
            reader = PdfReader(norm_path)
            pages = [p.extract_text() or '' for p in reader.pages]
            return "\n\n".join(t.strip() for t in pages if t.strip())
        elif ext == '.xlsx' or ext == '.xls':
            import pandas as pd
            df = pd.read_excel(norm_path)
            df = df.fillna('—') # Replace ugly NaN with clean em-dash

            # ANTES: solo las primeras 5 filas ("muestra") — cualquier pregunta sobre el
            # resto de una planilla real quedaba sin respuesta ("no puedo trabajar", bug
            # real reportado 31-ago). Ahora van TODAS las filas como texto plano: el RAG
            # las trocea y embebe por su cuenta, así cualquier fila es recuperable, no
            # solo las primeras 5. Tope de 5000 filas para no colgar con un archivo
            # gigante — si hace falta más, es un caso para DB-GPT (cruces exactos, fuera
            # de alcance de esta ronda), no para el RAG vectorial.
            MAX_ROWS = 5000
            truncated = len(df) > MAX_ROWS
            df_out = df.head(MAX_ROWS) if truncated else df

            headers = [str(c) for c in df.columns]
            lines = [f"**Planilla:** {len(df)} registros | {len(df.columns)} columnas ({', '.join(headers)})", ""]
            if truncated:
                lines.append(f"(mostrando las primeras {MAX_ROWS} de {len(df)} filas)")
                lines.append("")
            for _, row in df_out.iterrows():
                pares = [f"{h}: {str(v).strip()}" for h, v in zip(headers, row.values)]
                lines.append(" | ".join(pares))

            return "\n".join(lines)
        else:
            with open(norm_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read(2000)
    except Exception as e:
        return f"Error al procesar {os.path.basename(norm_path)}: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(extract_file_text(sys.argv[1]))
    else:
        print("No filepath provided")
