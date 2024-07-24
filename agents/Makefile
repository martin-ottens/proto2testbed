BASENAME = instance-manager

.PHONY clean

all: agent_manager.py control manager.service postinst
	mkdir -p $(BASENAME)/DEBIAN
	mkdir -p $(BASENAME)/usr/lib/instance-manager
	mkdir -p $(BASENAME)/lib/systemd/system
	cp control postinst $(BASENAME)/DEBIAN/.
	cp manager.service $(BASENAME)/lib/systemd/system/.
	cp agent_manager.py $(BASENAME)/usr/lib/instance-manager/.
	chmod +x $(BASENAME)/usr/lib/instance-manager/agent_manager.py
	dpkg-deb --build $(BASENAME)

clean:
	rm -rf $(BASENAME)
