const express = require('express');
const cors = require('cors');
const path = require('path');
const http = require('http');
const multer = require('multer');
const fs = require('fs');
const { execSync } = require('child_process');

const app = express();
const PORT = process.env.PORT || 8095;

const uploadDir = path.join(__dirname, 'public', 'uploads');
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

const DB_FILE = path.join(uploadDir, 'db_state.json');

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, uploadDir),
  filename: (req, file, cb) => {
    const rawName = Buffer.from(file.originalname, 'latin1').toString('utf8');
    cb(null, `${Date.now()}_${rawName}`);
  }
});
const upload = multer({ storage });

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

function extractText(filepath) {
  try {
    const pythonScript = path.join(__dirname, 'extract_text.py');
    const output = execSync(`python3 "${pythonScript}" "${filepath}"`, { encoding: 'utf-8' });
    return output.trim();
  } catch (err) {
    console.error('Error al extraer texto:', err.message);
    return null;
  }
}

// =========================================================================
// TARIFAS Y COSTOS DINÁMICOS POR CLIENTE (TENANT ELEA)
// =========================================================================
let clientProfile = {
  clientId: "elea_pharma",
  clientName: "Laboratorios ELEA",
  tier: "Enterprise Farma",
  currency: "USD",
  totalBudgetUsd: 500.0,
  ratesPer1kTokens: {
    "basa-auto-router": 0.010,
    "demo-gpt-4o": 0.025,
    "azure-gpt-4o-mini": 0.005,
    "deepseek-r1-distill": 0.008
  }
};

let config = {
  guardianGatewayUrl: 'http://localhost:4000/v1',
  guardianApiKey: 'sk-guardian-demo-key-2026',
  selectedGuardianModel: 'basa-auto-router',
  anythingLlmUrl: 'http://localhost:3001',
  anythingLlmApiKey: 'ANT-KEY-ELEA-PROD-2026',
  anythingLlmWorkspace: 'control-de-calidad-elea'
};

const initialUsersDB = {
  "ana.gomez": {
    id: "ana.gomez",
    name: "Dra. Ana Gómez",
    role: "Investigación & Desarrollo",
    email: "ana.gomez@elea.com",
    avatar: "AG",
    quotaUsd: 150.0,
    usedUsd: 14.50,
    currentWorkspaceId: "ws_calidad_elea",
    currentThreadId: "th_calidad_01",
    workspaces: [
      {
        id: "ws_calidad_elea",
        name: "Control de Calidad ELEA",
        description: "Espacio de control documental y contratos",
        ragMode: "strict", // "strict" (Query) or "conversational" (Chat)
        temperature: 0.1,
        systemPrompt: "Eres el asistente de Calidad y Farmacovigilancia de Laboratorios ELEA. Cita siempre la fuente documental.",
        created_at: "2026-08-27",
        documents: [],
        threads: [
          {
            id: "th_calidad_01",
            title: "Revisión Documental y Clientes",
            updated_at: "Hoy, 11:50",
            messages: [
              {
                role: "assistant",
                content: "¡Hola Dra. Ana Gómez! Estás en el espacio **Control de Calidad ELEA**. Los costos de tokens se calculan automáticamente con la **Tarifa Farma Enterprise** de ELEA. Puedes cargar archivos o hacer consultas directas.",
                engine: "Basa GuardIAn Auto-Router (:4000)",
                cost_usd: 0.0020
              }
            ]
          }
        ]
      }
    ]
  },
  "luis.fierro": {
    id: "luis.fierro",
    name: "Lic. Luis Fierro",
    role: "Garantía de Calidad",
    email: "luis.fierro@elea.com",
    avatar: "LF",
    quotaUsd: 100.0,
    usedUsd: 8.50,
    currentWorkspaceId: "ws_auditoria_planta",
    currentThreadId: "th_auditoria_01",
    workspaces: [
      {
        id: "ws_auditoria_planta",
        name: "Auditoría Planta Pilar",
        description: "Checklists de GMP y control de desviaciones",
        ragMode: "conversational",
        temperature: 0.2,
        systemPrompt: "Eres el auditor senior de planta farmacéutica.",
        created_at: "2026-08-25",
        documents: [],
        threads: [
          {
            id: "th_auditoria_01",
            title: "Control de Puntos Críticos Planta",
            updated_at: "Hoy, 07:15",
            messages: []
          }
        ]
      }
    ]
  },
  "cristian.luna": {
    id: "cristian.luna",
    name: "Lic. Cristian Luna",
    role: "Auditoría y Compliance",
    email: "cristian.luna@elea.com",
    avatar: "CL",
    quotaUsd: 100.0,
    usedUsd: 0.00,
    currentWorkspaceId: "ws_compliance",
    currentThreadId: "th_comp_01",
    workspaces: [
      {
        id: "ws_compliance",
        name: "Marco Regulatorio ANMAT",
        description: "Normativas y disposiciones ANMAT",
        ragMode: "strict",
        temperature: 0.0,
        systemPrompt: "Analista de regulaciones sanitarias ANMAT.",
        created_at: "2026-08-28",
        documents: [],
        threads: [
          {
            id: "th_comp_01",
            title: "Disposiciones 2026",
            updated_at: "Hoy, 08:30",
            messages: []
          }
        ]
      }
    ]
  }
};

let usersDB = initialUsersDB;
let currentUserId = "ana.gomez";
let isAuthenticated = true;

function loadDB() {
  try {
    if (fs.existsSync(DB_FILE)) {
      const data = JSON.parse(fs.readFileSync(DB_FILE, 'utf-8'));
      if (data.usersDB) usersDB = data.usersDB;
      else usersDB = data;
      if (data.config) config = { ...config, ...data.config };
      if (data.clientProfile) clientProfile = { ...clientProfile, ...data.clientProfile };
      console.log('✅ Base de datos cargada desde:', DB_FILE);
    } else {
      saveDB();
    }
  } catch (err) {
    console.error('Error al cargar base de datos:', err);
  }
}

function saveDB() {
  try {
    fs.writeFileSync(DB_FILE, JSON.stringify({ usersDB, config, clientProfile, currentUserId, isAuthenticated }, null, 2), 'utf-8');
  } catch (err) {
    console.error('Error al guardar base de datos:', err);
  }
}

loadDB();

// =========================================================================
// API ENDPOINTS
// =========================================================================

app.get('/api/config', (req, res) => res.json({ config, clientProfile }));

app.post('/api/config', (req, res) => {
  if (req.body.config) config = { ...config, ...req.body.config };
  if (req.body.clientProfile) clientProfile = { ...clientProfile, ...req.body.clientProfile };
  if (req.body.selectedGuardianModel) config.selectedGuardianModel = req.body.selectedGuardianModel;
  saveDB();
  res.json({ success: true, config, clientProfile });
});

// AUTHENTICATION (LOGIN / LOGOUT / CURRENT)
app.post('/api/auth/login', (req, res) => {
  const { userId } = req.body;
  if (usersDB[userId]) {
    currentUserId = userId;
    isAuthenticated = true;
    saveDB();
    return res.json({ success: true, user: usersDB[currentUserId], client: clientProfile });
  }
  res.status(401).json({ error: 'Credenciales o usuario no encontrado en GuardIAn' });
});

app.post('/api/auth/logout', (req, res) => {
  isAuthenticated = false;
  saveDB();
  res.json({ success: true, message: 'Sesión cerrada correctamente' });
});

app.get('/api/user/current', (req, res) => {
  const user = usersDB[currentUserId] || Object.values(usersDB)[0];
  const totalUsedByUsers = Object.values(usersDB).reduce((acc, u) => acc + (u.usedUsd || 0), 0);
  
  res.json({
    isAuthenticated: isAuthenticated,
    user: {
      id: user.id,
      name: user.name,
      role: user.role,
      email: user.email,
      avatar: user.avatar,
      quotaUsd: user.quotaUsd,
      usedUsd: user.usedUsd,
      currentWorkspaceId: user.currentWorkspaceId,
      currentThreadId: user.currentThreadId
    },
    client: {
      ...clientProfile,
      totalUsedUsd: parseFloat(totalUsedByUsers.toFixed(2))
    },
    workspaces: user.workspaces,
    availableUsers: Object.keys(usersDB).map(k => ({
      id: usersDB[k].id,
      name: usersDB[k].name,
      role: usersDB[k].role,
      email: usersDB[k].email,
      avatar: usersDB[k].avatar
    })),
    config: config
  });
});

app.post('/api/user/switch', (req, res) => {
  const { userId } = req.body;
  if (usersDB[userId]) {
    currentUserId = userId;
    isAuthenticated = true;
    saveDB();
    return res.json({ success: true, user: usersDB[currentUserId] });
  }
  res.status(404).json({ error: 'Usuario no encontrado' });
});

// WORKSPACE MANAGEMENT (CREATE, DELETE, SETTINGS)
app.post('/api/workspaces/create', (req, res) => {
  const { name, description, ragMode, temperature, systemPrompt } = req.body;
  const user = usersDB[currentUserId];
  const newWsId = `ws_${Date.now()}`;
  const newThreadId = `th_${Date.now()}`;

  const newWs = {
    id: newWsId,
    name: name || "Nuevo Espacio de Trabajo",
    description: description || "Espacio personalizado de investigación",
    ragMode: ragMode || "strict",
    temperature: typeof temperature === 'number' ? temperature : 0.1,
    systemPrompt: systemPrompt || "Eres un asistente de investigación de ELEA.",
    created_at: new Date().toISOString().split('T')[0],
    documents: [],
    threads: [
      {
        id: newThreadId,
        title: "Conversación Inicial",
        updated_at: "Recién",
        messages: [
          {
            role: "assistant",
            content: `¡Bienvenido al nuevo espacio **${name}**! Puedes subir documentos en el panel derecho para activar el motor RAG.`,
            engine: "AnythingLLM & GuardIAn Sync"
          }
        ]
      }
    ]
  };

  user.workspaces.unshift(newWs);
  user.currentWorkspaceId = newWsId;
  user.currentThreadId = newThreadId;
  saveDB();

  res.json({ success: true, workspace: newWs });
});

app.post('/api/workspaces/delete', (req, res) => {
  const { workspaceId } = req.body;
  const user = usersDB[currentUserId];
  if (user.workspaces.length <= 1) {
    return res.status(400).json({ error: 'Debe existir al menos un espacio de trabajo activo.' });
  }
  user.workspaces = user.workspaces.filter(w => w.id !== workspaceId);
  user.currentWorkspaceId = user.workspaces[0].id;
  user.currentThreadId = user.workspaces[0].threads[0] ? user.workspaces[0].threads[0].id : null;
  saveDB();
  res.json({ success: true, remainingWorkspaces: user.workspaces });
});

app.post('/api/workspaces/settings', (req, res) => {
  const { workspaceId, ragMode, temperature, systemPrompt } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === (workspaceId || user.currentWorkspaceId));
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });

  if (ragMode) ws.ragMode = ragMode;
  if (typeof temperature === 'number') ws.temperature = temperature;
  if (systemPrompt !== undefined) ws.systemPrompt = systemPrompt;
  saveDB();
  res.json({ success: true, workspace: ws });
});

// THREAD MANAGEMENT (CREATE, RENAME, CLEAR, DELETE)
app.post('/api/threads/create', (req, res) => {
  const { workspaceId, title } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === (workspaceId || user.currentWorkspaceId));
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });

  const newThreadId = `th_${Date.now()}`;
  const newThread = {
    id: newThreadId,
    title: title || `Nuevo Hilo #${ws.threads.length + 1}`,
    updated_at: "Recién",
    messages: [
      {
        role: "assistant",
        content: `Nuevo hilo creado en el espacio **${ws.name}**. ¿Qué deseas analizar?`,
        engine: "Basa GuardIAn Gateway"
      }
    ]
  };

  ws.threads.unshift(newThread);
  user.currentThreadId = newThreadId;
  saveDB();

  res.json({ success: true, thread: newThread });
});

app.post('/api/threads/rename', (req, res) => {
  const { threadId, title } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });
  const thread = ws.threads.find(t => t.id === threadId);
  if (!thread) return res.status(404).json({ error: 'Hilo no encontrado' });

  thread.title = title || thread.title;
  saveDB();
  res.json({ success: true, thread });
});

app.post('/api/threads/clear', (req, res) => {
  const { threadId } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });
  const thread = ws.threads.find(t => t.id === (threadId || user.currentThreadId));
  if (!thread) return res.status(404).json({ error: 'Hilo no encontrado' });

  thread.messages = [
    {
      role: 'assistant',
      content: `🧹 Chat limpiado. Puedes iniciar una nueva consulta en el espacio **${ws.name}**.`,
      engine: 'Basa GuardIAn Auto-Router'
    }
  ];
  saveDB();
  res.json({ success: true, thread });
});

app.post('/api/threads/delete', (req, res) => {
  const { threadId } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });

  if (ws.threads.length <= 1) {
    ws.threads = [{
      id: `th_${Date.now()}`,
      title: "Conversación Principal",
      updated_at: "Recién",
      messages: []
    }];
  } else {
    ws.threads = ws.threads.filter(t => t.id !== threadId);
  }
  user.currentThreadId = ws.threads[0].id;
  saveDB();
  res.json({ success: true, remainingThreads: ws.threads });
});

app.post('/api/session/select', (req, res) => {
  const { workspaceId, threadId } = req.body;
  const user = usersDB[currentUserId];
  if (workspaceId) user.currentWorkspaceId = workspaceId;
  if (threadId) user.currentThreadId = threadId;
  saveDB();
  res.json({ success: true, currentWorkspaceId: user.currentWorkspaceId, currentThreadId: user.currentThreadId });
});

// DOCUMENT MANAGEMENT (UPLOAD, DELETE, PREVIEW)
app.post('/api/workspaces/upload', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No se recibió archivo' });

  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  const rawName = Buffer.from(req.file.originalname, 'latin1').toString('utf8');
  const ext = path.extname(rawName).toLowerCase().replace('.', '');
  const savedPath = req.file.path;

  const extractedText = extractText(savedPath);

  const newDoc = {
    id: `doc_${Date.now()}`,
    name: rawName,
    storedFilename: req.file.filename,
    type: ext,
    pages: ext === 'docx' ? 4 : (ext === 'pdf' ? 14 : null),
    rows: (ext === 'xlsx' || ext === 'csv') ? 373 : null,
    size: `${(req.file.size / 1024).toFixed(1)} KB`,
    date: new Date().toISOString().split('T')[0],
    extractedText: extractedText
  };

  if (ws) {
    ws.documents.push(newDoc);
  }
  saveDB();

  res.json({
    success: true,
    document: newDoc,
    message: `Documento "${rawName}" indexado correctamente.`
  });
});

app.post('/api/workspaces/documents/delete', (req, res) => {
  const { documentName, documentId } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  if (!ws) return res.status(404).json({ error: 'Workspace no encontrado' });

  ws.documents = ws.documents.filter(d => (documentId ? d.id !== documentId : d.name !== documentName));
  saveDB();
  res.json({ success: true, remainingDocuments: ws.documents });
});

app.post('/api/chat', (req, res) => {
  const { message, guardian_model } = req.body;
  const user = usersDB[currentUserId];
  const ws = user.workspaces.find(w => w.id === user.currentWorkspaceId);
  const thread = ws ? ws.threads.find(t => t.id === user.currentThreadId) : null;

  const selectedModel = guardian_model || config.selectedGuardianModel || 'basa-auto-router';

  // Cost according to client rate
  const ratePer1k = clientProfile.ratesPer1kTokens[selectedModel] || 0.010;
  const estimatedTokens = 400;
  const queryCost = parseFloat(((estimatedTokens / 1000) * ratePer1k).toFixed(4));

  if (thread) {
    thread.messages.push({ role: 'user', content: message, timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) });
  }

  user.usedUsd = parseFloat(((user.usedUsd || 0) + queryCost).toFixed(4));

  // A. RAG Documental
  if (ws && ws.documents && ws.documents.length > 0) {
    let docSummaries = [];
    let citations = [];

    ws.documents.forEach((doc) => {
      let text = '';
      if (doc.storedFilename && fs.existsSync(path.join(uploadDir, doc.storedFilename))) {
        text = extractText(path.join(uploadDir, doc.storedFilename));
        doc.extractedText = text;
      } else {
        text = doc.extractedText || '';
      }

      if (text) {
        if (doc.type === 'docx' || doc.type === 'pdf' || doc.type === 'txt') {
          const lines = text.split('\n').filter(l => l.trim().length > 0);
          const points = lines.slice(0, 5).map(l => `• ${l}`).join('\n');
          docSummaries.push(`### 📄 Documento: ${doc.name}\n\n${points}`);
          citations.push({
            document: doc.name,
            page: "Pág. 1",
            section: lines[0] ? lines[0].substring(0, 60) : "Cláusulas Principales"
          });
        } else if (doc.type === 'xlsx' || doc.type === 'csv') {
          docSummaries.push(`### 📊 Planilla de Datos: ${doc.name}\n\n${text}`);
          citations.push({
            document: doc.name,
            page: "Hoja 1 (373 Filas)",
            section: "Estructura de Registros y Contactos"
          });
        }
      } else {
        docSummaries.push(`### 📁 ${doc.name} (${doc.type.toUpperCase()})`);
        citations.push({ document: doc.name, page: "Indexado", section: "Documento en Workspace" });
      }
    });

    const ragModeLabel = ws.ragMode === 'strict' ? '🎯 RAG Estricto (Query Mode)' : '💬 RAG Conversacional (Chat Mode)';
    const responseContent = `**[${ragModeLabel} · ${selectedModel.toUpperCase()} · Tarifa ${clientProfile.tier}]**\n\nEn el espacio **"${ws.name}"** se encuentran indexados **${ws.documents.length} documento(s)**. Costo de consulta: $${queryCost.toFixed(4)} USD.\n\n${docSummaries.join('\n\n---\n\n')}`;

    const reply = {
      role: 'assistant',
      content: responseContent,
      sources: citations,
      cost_usd: queryCost,
      timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
      engine: `Basa GuardIAn Gateway [${selectedModel}] + AnythingLLM RAG (:3001)`
    };
    if (thread) thread.messages.push(reply);
    saveDB();
    return res.json(reply);
  }

  // B. Respuesta General
  const generalReply = {
    role: 'assistant',
    content: `Hola ${user.name}. En el espacio **"${ws ? ws.name : 'General'}"** aún no hay documentos subidos. Procesado con tarifa **${clientProfile.tier}** ($${queryCost.toFixed(4)} USD).`,
    cost_usd: queryCost,
    timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
    engine: `Basa GuardIAn Gateway [${selectedModel}] (:4000)`
  };
  if (thread) thread.messages.push(generalReply);
  saveDB();
  res.json(generalReply);
});

app.listen(PORT, () => {
  console.log(`=======================================================`);
  console.log(`🚀 Elea Portal (Full Enterprise Suite) en http://localhost:${PORT}`);
  console.log(`=======================================================`);
});
