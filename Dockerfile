ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

RUN apk add --update --no-cache  \
        jq                       \
        python3                  \
 && mkdir /app                   \
 && cd /app                      \
 && python3 -m venv venv         \
 && source venv/bin/activate     \
 && python3 -m ensurepip         \ 
 && pip3 install --upgrade pip   \
 && pip3 install paho-mqtt

COPY run.sh monitor.py /app/

WORKDIR /app

CMD ["./run.sh"]
