importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyCys1Wx2c_O66sdbMrfLmqPnXyxRcli7EI",
  authDomain: "jadwalku-270ce.firebaseapp.com",
  projectId: "jadwalku-270ce",
  storageBucket: "jadwalku-270ce.firebasestorage.app",
  messagingSenderId: "582319035259",
  appId: "1:582319035259:web:a5af8c4b51f53c659e63de"
});

var messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload){
  var n = payload.notification || {};
  self.registration.showNotification(n.title || "Jadwal Al Mukarram", {
    body: n.body || ""
  });
});
