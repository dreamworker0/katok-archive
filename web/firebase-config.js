/* Firebase 웹 설정.
 *
 * apiKey 는 비밀이 아니다 — 프로젝트를 가리키는 공개 식별자이며, 실제 접근 통제는
 * firestore.rules / storage.rules 가 담당한다. 그래서 저장소에 두어도 안전하다.
 * (참고: Firebase 공식 문서 "Firebase API keys are not secrets")
 */
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyBx53IErOFOdzziz9WTm0OIy2Uyq_jxCyc",
  authDomain: "katok-crawling-project.firebaseapp.com",
  projectId: "katok-crawling-project",
  storageBucket: "katok-crawling-project.firebasestorage.app",
  messagingSenderId: "460921338745",
  appId: "1:460921338745:web:d463c217c50b2181174da8",
};
