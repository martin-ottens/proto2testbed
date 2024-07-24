BASENAME = instance-manager

.PHONY: clean

all: manager_main.py control manager.service postinst
	mkdir -p $(BASENAME)/DEBIAN
	mkdir -p $(BASENAME)/usr/lib/instance-manager
	mkdir -p $(BASENAME)/lib/systemd/system
	cp control postinst $(BASENAME)/DEBIAN/.
	cp manager.service $(BASENAME)/lib/systemd/system/.
	cp manager_main.py $(BASENAME)/usr/lib/instance-manager/.
	dpkg-deb --build $(BASENAME)

clean:
	rm -rf $(BASENAME) $(BASENAME).deb
