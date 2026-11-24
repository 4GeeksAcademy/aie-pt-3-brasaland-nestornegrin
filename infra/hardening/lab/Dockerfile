# Laboratorio: un Ubuntu 24.04 REAL, sin endurecer a propósito (root por SSH y contraseñas permitidas), donde se aplica
# infra/hardening/harden-server.sh y se demuestra el antes/después. La contraseña de root es de usar y tirar y el puerto
# solo se publica en 127.0.0.1 (ver run-lab.sh). No es una imagen para producción.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server ufw sudo iproute2 iptables netcat-openbsd openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /root/.ssh \
    && echo 'root:lab-sin-endurecer' | chpasswd \
    && printf 'PermitRootLogin yes\nPasswordAuthentication yes\n' > /etc/ssh/sshd_config.d/50-lab-inseguro.conf
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
