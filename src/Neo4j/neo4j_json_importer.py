
import json
import os
from neo4j import GraphDatabase

class Neo4jImporter:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def import_files(self, folder_path):
        for filename in os.listdir(folder_path):
            if filename.endswith(".json"):
                print(f"--- Processing {filename} ---")
                self._process_file(os.path.join(folder_path, filename))

    def _process_file(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        graph_data = data.get('@graph', [])
        
        with self.driver.session() as session:
            for record in graph_data:
                session.execute_write(self._upsert_node, record)

    @staticmethod
    def _upsert_node(tx, record):
        node_id = record.get('@id')
        labels = record.get('@type', ['Entity'])
        if isinstance(labels, str): labels = [labels]
        
        clean_labels = ":".join([f"`{l}`" for l in labels])
        
        properties = {}
        for k, v in record.items():
            if k.startswith('@'): continue
            if isinstance(v, (dict, list)):
                properties[k] = json.dumps(v)
            else:
                properties[k] = v

        query = (
            f"MERGE (n:{clean_labels} {{id: $node_id}}) "
            f"SET n += $props "
            f"RETURN n.id as id"
        )
        tx.run(query, node_id=node_id, props=properties)


if __name__ == "__main__":
    URI = "bolt://localhost:7687"
    USER = "neo4j"
    PWD = "password"
    JSON_FOLDER = "../Backend/trip-planner/bayerncloud-data"

    importer = Neo4jImporter(URI, USER, PWD)
    try:
        importer.import_files(JSON_FOLDER)
        print("\nSuccess: All files processed.")
    finally:
        importer.close()


