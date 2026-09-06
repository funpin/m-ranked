import org.springframework.security.crypto.bcrypt.BCrypt;

/** Test fixture helper. The caller captures the hash; plaintext is environment-only. */
class AdminFixturePassword {
    public static void main(String[] args) {
        String password=System.getenv("MRANKED_FIXTURE_PASSWORD");
        if(password==null || password.length()<16) throw new IllegalArgumentException("A random fixture password is required");
        System.out.print("{bcrypt}"+BCrypt.hashpw(password,BCrypt.gensalt(4)));
    }
}
