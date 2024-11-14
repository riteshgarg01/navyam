# Use an official Python runtime as the base image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Upgrade pip to the latest version
RUN python -m pip install --upgrade pip

# Install dependencies
RUN apt-get update && apt-get install -y libpq-dev gcc

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port that the Flask app runs on
EXPOSE 8000

# Define environment variable for Flask to run in production mode
#ENV FLASK_ENV=production
#ENV FLASK_DEBUG=1
ENV FLASK_APP=app.py
#Default to 80 for production
ENV GUNICORN_PORT=80

# Run the application using Gunicorn as the WSGI server
CMD ["gunicorn", "-b", "0.0.0.0:${GUNICORN_PORT}", "app:app"]