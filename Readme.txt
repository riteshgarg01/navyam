Commands to setup
- ./app.py - to run the flask server
- ngrok http 5000

ssh -R navyam:80:localhost:8000 serveo.net
https://navyam.serveo.net/


$env:FLASK_DEBUG="1"
$env:FLASK_ENV="development"
$env:FLASK_APP="app.py"
flask run

psql -U riteshgarg / Cricket123
command to quit: \q

                            

Common errors & resolutions:
- riteshgarg@Arohi:/mnt/c/Users/arohi/Navyam$ psql postgresql://postgres:Cricket123@database-1.cpa6i22wu9wc.us-east-1.rds.amazonaws.com:5432/navyam
psql: error: connection to server at "database-1.cpa6i22wu9wc.us-east-1.rds.amazonaws.com" (54.163.234.236), port 5432 failed: Connection timed out
        Is the server running on that host and accepting TCP/IP connections?

RESOLUTION: Edit inbound rule to add My IP again


.env.dev file is used for development environment
.env file is used for production environment

To run development environment:
docker-compose up -d 
-- this will run the flask app on port 8000 and postgres on port 5432
to check the database in docker container:
docker exec -it navyam-postgres-1 psql -U postgres -d navyam

To run production environment which is powered by github actions:
--- just re-run the workflow in github actions


