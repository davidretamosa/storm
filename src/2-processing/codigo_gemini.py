import re
import json
import pandas as pd
import networkx as nx
from jinja2 import Template
from typing import List, Dict

# =====================================================================
# 1. PARSING: Extracción de Endpoints del .jar y Procesamiento de Logs
# =====================================================================
class DataParser:
    """Extrae la estructura del .jar y procesa las peticiones de los logs."""[cite: 1]
    
    @staticmethod
    def parse_logs(log_file_path: str) -> pd.DataFrame:
        """Convierte líneas de log en un DataFrame estructurado."""
        # Regex para capturar: Timestamp, Session_ID, HTTP Method, Endpoint
        log_pattern = r'(?P<timestamp>\S+) \[(?P<session_id>\w+)\] "(?P<method>GET|POST|PUT|DELETE) (?P<endpoint>\/\S*)"'
        
        parsed_data = []
        with open(log_file_path, 'r') as f:
            for line in f:
                match = re.search(log_pattern, line)
                if match:
                    parsed_data.append(match.groupdict())
                    
        df = pd.DataFrame(parsed_data)
        return df

# =====================================================================
# 2. PATTERN ANALYSIS & MODELING: Cadenas de Markov y Tiempos de Carga
# =====================================================================
class AITrafficModeler:
    """Aplica grafos y probabilidad de Markov para modelar patrones de tráfico."""[cite: 1]
    
    def __init__(self, df_logs: pd.DataFrame):
        self.df = df_logs

    def build_markov_matrix(self) -> Dict[str, Dict[str, float]]:
        """Calcula la probabilidad de transición entre endpoints seguidos."""
        # Ordenar logs por sesión para reconstruir la secuencia de navegación
        self.df['next_endpoint'] = self.df.groupby('session_id')['endpoint'].shift(-1)
        
        # Filtrar el último paso de cada sesión
        transitions = self.df.dropna(subset=['next_endpoint'])
        
        # Contar ocurrencias de Endpoint A -> Endpoint B
        counts = transitions.groupby(['endpoint', 'next_endpoint']).size().unstack(fill_value=0)
        
        # Normalizar para obtener probabilidades (suman 1 por fila)
        probabilities = counts.div(counts.sum(axis=1), axis=0).fillna(0)
        
        return probabilities.to_dict(orient='index')

    def predict_traffic_scale((self) -> Dict[str, int]:
        """Calcula el número de usuarios virtuales y la rampa de escalado necesaria."""
        unique_sessions = self.df['session_id'].nunique()
        # Algoritmo predictivo simplificado: Escala proyectada para simulación de estrés
        target_vusers = int(unique_sessions * 1.5)  # Proyección de +50% de tráfico
        
        return {
            "vusers": target_vusers,
            "ramp_up_seconds": 60,
            "duration_seconds": 300
        }

# =====================================================================
# 3. SCENARIO GENERATION: Generación de artefactos JMX e instrucciones K8s
# =====================================================================
class ScenarioGenerator:
    """Genera las guías de trafico (.jmx) e instrucciones para Kubernetes."""[cite: 1]
    
    JMX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="AI Traffic Plan">
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments">
        <collectionProp name="Arguments.arguments"/>
      </elementProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="AI Users">
        <intProp name="ThreadGroup.num_threads">{{ vusers }}</intProp>
        <intProp name="ThreadGroup.ramp_time">{{ ramp_up }}</intProp>
        <boolProp name="ThreadGroup.same_user_on_next_iteration">true</boolProp>
      </ThreadGroup>
      <hashTree>
        {% for source, targets in markov_matrix.items() %}
          {% for target, prob in targets.items() %}
            {% if prob > 0.1 %}
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="{{ source }} -> {{ target }}">
          <stringProp name="HTTPSampler.path">{{ target }}</stringProp>
          <stringProp name="HTTPSampler.method">GET</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
            {% endif %}
          {% endfor %}
        {% endfor %}
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"""

    @classmethod
    def generate_jmx(cls, markov_matrix: dict, profile: dict, output_path: str):
        """Compila la plantilla XML de JMeter con las distribuciones de la IA."""[cite: 1]
        template = Template(cls.JMX_TEMPLATE)
        rendered_jmx = template.render(
            vusers=profile['vusers'],
            ramp_up=profile['ramp_up_seconds'],
            markov_matrix=markov_matrix
        )
        with open(output_path, 'w') as f:
            f.write(rendered_jmx)
            
    @classmethod
    def generate_k8s_instructions(cls, profile: dict, output_path: str):
        """Genera el manifiesto de escalado para Kubernetes."""[cite: 1]
        # Regla: 1 Pod de JMeter por cada 500 usuarios virtuales
        replicas = (profile['vusers'] // 500) + 1
        
        k8s_config = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "jmeter-load-generator"},
            "spec": {
                "replicas": replicas,
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "jmeter-worker",
                            "image": "justb4/jmeter:latest",
                            "resources": {
                                "limits": {"cpu": "2000m", "memory": "2Gi"}
                            }
                        }]
                    }
                }
            }
        }
        with open(output_path, 'w') as f:
            json.dump(k8s_config, f, indent=2)

# =====================================================================
# EJECUCIÓN PRINCIPAL DEL ORQUESTADOR
# =====================================================================
if __name__ == "__main__":
    print("--- 1. PARSING ---")[cite: 1]
    # Simulamos la lectura de logs extraídos del sistema
    df_logs = DataParser.parse_logs("sample_app.log")
    
    print("--- 2. PATTERN ANALYSIS & MODELING ---")[cite: 1]
    modeler = AITrafficModeler(df_logs)
    markov_matrix = modeler.build_markov_matrix()
    scaling_profile = modeler.predict_traffic_scale()
    
    print(f"Tráfico Proyectado: {scaling_profile['vusers']} usuarios virtuales.")
    
    print("--- 3. SCENARIO GENERATION & SCHEDULING ---")[cite: 1]
    # Exporta las guías para JMeter/Docker y Kubernetes
    ScenarioGenerator.generate_jmx(markov_matrix, scaling_profile, "generated_scenario.jmx")
    ScenarioGenerator.generate_k8s_instructions(scaling_profile, "k8s_deployment.json")
    
    print("PROCESO COMPLETADO: Archivos .jmx y manifiestos K8s generados.")[cite: 1]