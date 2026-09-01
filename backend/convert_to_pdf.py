from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import re

def markdown_to_pdf(md_file, pdf_file):
    # Read markdown file
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Create PDF
    doc = SimpleDocTemplate(pdf_file, pagesize=letter,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=18)
    
    # Container for 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CustomTitle', 
                             parent=styles['Heading1'],
                             fontSize=16,
                             textColor='black',
                             spaceAfter=12,
                             alignment=TA_CENTER,
                             bold=True))
    
    styles.add(ParagraphStyle(name='CustomHeading', 
                             parent=styles['Heading2'],
                             fontSize=12,
                             textColor='black',
                             spaceAfter=8,
                             spaceBefore=12,
                             bold=True))
    
    # Parse markdown and convert to PDF elements
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            elements.append(Spacer(1, 0.1*inch))
            i += 1
            continue
        
        # H1 (# Title)
        if line.startswith('# '):
            text = line[2:].strip()
            elements.append(Paragraph(text, styles['CustomTitle']))
            elements.append(Spacer(1, 0.2*inch))
        
        # H2 (## Heading)
        elif line.startswith('## '):
            text = line[3:].strip()
            elements.append(Paragraph(text, styles['CustomHeading']))
        
        # Horizontal rule
        elif line.startswith('---'):
            elements.append(Spacer(1, 0.2*inch))
        
        # Bold text
        elif line.startswith('**') and line.endswith('**'):
            text = line[2:-2]
            elements.append(Paragraph(f'<b>{text}</b>', styles['Normal']))
        
        # Bullet points
        elif line.startswith('- '):
            text = line[2:].strip()
            # Handle bold in bullet points
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            elements.append(Paragraph(f'• {text}', styles['Normal']))
        
        # Italic text (references)
        elif line.startswith('*') and not line.startswith('**'):
            text = line.strip('*').strip()
            elements.append(Paragraph(f'<i>{text}</i>', styles['Normal']))
        
        # Regular paragraph
        else:
            # Handle bold text inline
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            # Handle italic text inline
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            # Escape special characters
            text = text.replace('&', '&amp;')
            elements.append(Paragraph(text, styles['Normal']))
        
        i += 1
    
    # Build PDF
    doc.build(elements)
    print(f"PDF created successfully: {pdf_file}")

if __name__ == "__main__":
    markdown_to_pdf("Flawed_Agreement.md", "Flawed_Agreement.pdf")
