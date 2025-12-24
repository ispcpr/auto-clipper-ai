# Use official Python image
FROM python:3.11

# Install system dependencies
# ca-certificates for SSL, ffmpeg for media, dnsutils/ping for debug
RUN apt-get update && apt-get install -y \
    ffmpeg \
    ca-certificates \
    dnsutils \
    iputils-ping \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set up a non-root user with UID 1000 (standard for HF Spaces)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Set working directory to the user's home/app
WORKDIR $HOME/app

# Copy requirements and install python dependencies
# Copying as user to avoid permission issues
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy the rest of the application code
COPY --chown=user . .

# Create directories for downloads and output
RUN mkdir -p downloads output_clips

# Expose Streamlit port
EXPOSE 7860

# Run the application
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
