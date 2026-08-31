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
        elif ext == '.xlsx' or ext == '.xls':
            import pandas as pd
            df = pd.read_excel(norm_path)
            df = df.fillna('—') # Replace ugly NaN with clean em-dash
            
            # Create a clean markdown table of the first 5 rows
            headers = [str(c) for c in df.columns]
            header_row = "| " + " | ".join(headers) + " |"
            sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
            
            sample_rows = []
            for _, row in df.head(5).iterrows():
                sample_rows.append("| " + " | ".join(str(val).strip() for val in row.values) + " |")
            
            md_table = "\n".join([header_row, sep_row] + sample_rows)
            
            summary = f"**Planilla:** {len(df)} registros | {len(df.columns)} columnas ({', '.join(headers)})\n\n{md_table}"
            return summary
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
