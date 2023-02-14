var hash_active = new Array();

function init() {
	let hash = document.location.hash;

	while (hash_active.length) {
		let oldnode = hash_active.pop();
		oldnode.classList.remove("hash-active");
	}

	if (hash.startsWith("#")) {
		let loc = CSS.escape(hash.substr(1));
		for (let node of Array.from(document.querySelectorAll(`a[name='${loc}']`))) {
			console.log(node);
			node.classList.add("hash-active");
			hash_active.push(node);
		}
	}
}

document.onload = init;
window.onhashchange = init;
