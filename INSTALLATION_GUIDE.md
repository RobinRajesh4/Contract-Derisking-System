# Contract Derisking System - Installation Guide

## Overview
The Contract Derisking System is a full-stack application that analyzes legal contracts for potential risks using AI/ML technologies. It consists of:
- **Frontend**: React + TypeScript + Vite with shadcn/ui components
- **Backend**: FastAPI Python server with OCR capabilities
- **AI Features**: Contract analysis, risk assessment, and recommendations

## Prerequisites

### System Requirements
- **Operating System**: Windows 10/11, macOS 10.15+, or Linux (Ubuntu 18.04+)
- **RAM**: Minimum 4GB (8GB recommended)
- **Storage**: 2GB free space
- **Internet**: Required for AI model downloads and API calls

### Required Software

#### 1. Node.js (v18 or higher)
- **Download**: https://nodejs.org/
- **Installation**: Download and run the installer
- **Verification**: Open terminal and run `node --version` and `npm --version`

#### 2. Python (v3.9 or higher)
- **Download**: https://www.python.org/downloads/
- **Installation**: 
  - Download and run the installer
  - **Important**: Check "Add Python to PATH" during installation
- **Verification**: Open terminal and run `python --version` or `python3 --version`

#### 3. Git (for version control)
- **Download**: https://git-scm.com/downloads
- **Installation**: Download and run the installer
- **Verification**: Run `git --version`

## Installation Steps

### Step 1: Extract the Project
1. Download the project ZIP file
2. Extract it to your desired location (e.g., `C:\Projects\contract-derisking`)
3. Navigate to the project directory in your terminal

### Step 2: Install Frontend Dependencies
```bash
# Navigate to project root (if not already there)
cd contract-derisking

# Install Node.js dependencies
npm install
```

### Step 3: Install Backend Dependencies
```bash
# Navigate to backend directory
cd backend

# Create Python virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Return to project root
cd ..
```

### Step 4: Install OCR Software (Windows Only)

#### Tesseract OCR (Required for scanned PDFs)
1. **Download**: https://github.com/UB-Mannheim/tesseract/wiki
2. **Install**:
   - Download the latest Windows installer (e.g., `tesseract-ocr-w64-setup-5.x.x.exe`)
   - Run the installer with default settings
   - Note the installation path (usually: `C:\Program Files\Tesseract-OCR\`)
3. **Add to PATH**:
   - Right-click "This PC" → Properties → Advanced system settings
   - Click "Environment Variables"
   - Under "System variables", find "Path" and click "Edit"
   - Add new entry: `C:\Program Files\Tesseract-OCR`
4. **Verify**: Open new terminal and run `tesseract --version`

#### Poppler (Required for PDF to image conversion)
1. **Download**: httpblog.alivate.com.au/poppler-windows/
2. **Install**:
   - Download and extract to `C:\poppler\`
   - Ensure the path is: `C:\poppler\poppler-25.12.0\Library\bin`

### Step 5: Environment Configuration

#### Backend Environment Variables
Create a file `backend/.env` with the following:
```env
# AI Provider Settings (choose one)
GROQ_API_KEY=your_groq_api_key_here
# OR
OLLAMA_BASE_URL=http://localhost:11434

# Vector Database (optional)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your_qdrant_key_here

# Other settings
DEBUG=false
```

#### Frontend Environment Variables
Create a file `.env` in the project root:
```env
VITE_API_BASE_URL=http://localhost:8000
```

### Step 6: Start the Application

#### Method 1: Manual Start
```bash
# Terminal 1: Start Backend
cd backend
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux
uvicorn app.main:app --reload

# Terminal 2: Start Frontend (new terminal)
cd contract-derisking
npm run dev
```

#### Method 2: Using Batch Files (Windows)
1. **Start Backend**: Double-click `start_backend.bat`
2. **Start Frontend**: Double-click `run_project.bat`

### Step 7: Access the Application
- **Frontend**: http://localhost:8080
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## Optional Components

### Ollama (Local AI Models)
If you want to use local AI models instead of cloud APIs:
1. **Download**: https://ollama.ai/
2. **Install**: Download and run the installer
3. **Pull Models**: `ollama pull llama2` or `ollama pull mistral`
4. **Update Environment**: Set `OLLAMA_BASE_URL=http://localhost:11434` in `backend/.env`

### Qdrant (Vector Database)
For advanced RAG (Retrieval-Augmented Generation) features:
1. **Download**: https://qdrant.tech/
2. **Install**: Follow the installation guide for your OS
3. **Update Environment**: Set QDRANT_URL in `backend/.env`

## Troubleshooting

### Common Issues

#### 1. "Tesseract not found" Error
- **Solution**: Ensure Tesseract is installed and added to PATH
- **Alternative**: The app will still work for text-based PDFs

#### 2. "Python not found" Error
- **Solution**: Reinstall Python with "Add to PATH" checked
- **Verification**: Run `python --version` in terminal

#### 3. "Node not found" Error
- **Solution**: Reinstall Node.js
- **Verification**: Run `node --version` in terminal

#### 4. Port Already in Use
- **Solution**: Change ports in `vite.config.ts` (frontend) and backend startup command
- **Alternative**: Kill processes using the ports

#### 5. Module Import Errors
- **Backend**: Ensure virtual environment is activated
- **Frontend**: Run `npm install` again

### Log Locations
- **Backend Logs**: Console output from uvicorn server
- **Frontend Logs**: Browser developer console (F12)

## File Structure
```
contract-derisking/
├── backend/                 # Python FastAPI server
│   ├── app/                # Application code
│   ├── requirements.txt    # Python dependencies
│   └── .env               # Backend environment variables
├── src/                   # React frontend source
├── public/                # Static assets
├── package.json          # Node.js dependencies
├── vite.config.ts        # Vite configuration
├── .env                  # Frontend environment variables
└── README.md            # Project documentation
```

## Development Tips

### Running Tests
```bash
# Frontend tests
npm test

# Backend tests (if available)
cd backend
python -m pytest
```

### Code Formatting
```bash
# Frontend
npm run lint

# Backend (if using black/flake8)
cd backend
black .
flake8 .
```

### Building for Production
```bash
# Frontend
npm run build

# Backend (create requirements.txt)
pip freeze > requirements.txt
```

## Support

For issues:
1. Check the troubleshooting section above
2. Review the console logs for error messages
3. Verify all prerequisites are installed correctly
4. Ensure environment variables are set properly

## Next Steps

After successful installation:
1. Upload a sample contract PDF
2. Explore the analysis features
3. Configure AI providers (Groq, Ollama, etc.)
4. Set up custom risk assessment policies
5. Explore the API documentation at http://localhost:8000/docs
