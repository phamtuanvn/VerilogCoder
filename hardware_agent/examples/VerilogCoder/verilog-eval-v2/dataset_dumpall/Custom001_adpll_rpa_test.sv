`timescale 1ns/1ps

module tb;
    // DUT ports
    reg         clk;
    reg         reset;
    reg  [31:0] fcw;
    wire [31:0] phr;
    wire [7:0]  phr_int;
    wire [23:0] phr_frac;

    // Instantiate DUT
    TopModule dut (
        .clk      (clk),
        .reset    (reset),
        .fcw      (fcw),
        .phr      (phr),
        .phr_int  (phr_int),
        .phr_frac (phr_frac)
    );

    // Clock: 50MHz (20ns period)
    initial clk = 0;
    always #10 clk = ~clk;

    integer failed = 0;
    integer i;
    reg [31:0] expected_phr;

    task check;
        input [31:0] exp_phr;
        input [31:0] cycle;
        begin
            if (phr !== exp_phr) begin
                $display("FAIL cycle=%0d: phr=%h, expected=%h", cycle, phr, exp_phr);
                failed = failed + 1;
            end
            if (phr_int !== exp_phr[31:24]) begin
                $display("FAIL cycle=%0d: phr_int=%h, expected=%h", cycle, phr_int, exp_phr[31:24]);
                failed = failed + 1;
            end
            if (phr_frac !== exp_phr[23:0]) begin
                $display("FAIL cycle=%0d: phr_frac=%h, expected=%h", cycle, phr_frac, exp_phr[23:0]);
                failed = failed + 1;
            end
        end
    endtask

    initial begin
        // -----------------------------------------------
        // Test 1: Reset behavior
        // -----------------------------------------------
        reset = 1; fcw = 32'h0080_0000; // FCW = 0.5 in 8i+24f
        @(posedge clk); #1;
        check(32'h0, 0);

        @(posedge clk); #1;
        check(32'h0, 1);

        // -----------------------------------------------
        // Test 2: Basic accumulation with FCW = 1.0 (32'h0100_0000)
        // Each cycle phr increments by 1.0
        // -----------------------------------------------
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;

        for (i = 0; i < 8; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0100_0000;
            check(expected_phr, i);
        end

        // -----------------------------------------------
        // Test 3: Fractional accumulation FCW = 0.5 (32'h0080_0000)
        // -----------------------------------------------
        reset = 1;
        @(posedge clk); #1;
        reset = 0; fcw = 32'h0080_0000;
        expected_phr = 32'h0;

        for (i = 0; i < 6; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0080_0000;
            check(expected_phr, i);
        end

        // -----------------------------------------------
        // Test 4: Overflow wrap-around (modulo 2^32)
        // Set phr close to overflow: FCW = 32'hFFFF_FFFF
        // -----------------------------------------------
        reset = 1;
        @(posedge clk); #1;
        reset = 0; fcw = 32'hFFFF_FFFF;
        expected_phr = 32'h0;

        for (i = 0; i < 4; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'hFFFF_FFFF; // natural 32-bit wrap
            check(expected_phr, i);
        end

        // -----------------------------------------------
        // Test 5: Synchronous reset mid-operation
        // -----------------------------------------------
        reset = 1;
        @(posedge clk); #1;
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;

        repeat (3) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0100_0000;
        end
        check(expected_phr, 99);

        // Apply reset mid-run
        reset = 1;
        @(posedge clk); #1;
        check(32'h0, 100); // must be 0 after sync reset

        reset = 0;
        @(posedge clk); #1;
        check(32'h0100_0000, 101); // resumes accumulation

        // -----------------------------------------------
        // Test 6: FCW change mid-run
        // -----------------------------------------------
        reset = 1;
        @(posedge clk); #1;
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;

        repeat (2) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0100_0000;
        end

        fcw = 32'h0200_0000; // change FCW
        repeat (2) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0200_0000;
        end
        check(expected_phr, 110);

        // -----------------------------------------------
        // Test 7: FCW = 0 (no accumulation)
        // -----------------------------------------------
        reset = 1;
        @(posedge clk); #1;
        reset = 0; fcw = 32'h0;
        @(posedge clk); #1;
        check(32'h0, 120);
        @(posedge clk); #1;
        check(32'h0, 121);

        // -----------------------------------------------
        // Result
        // -----------------------------------------------
        if (failed == 0)
            $display("Function Check Success");
        else
            $display("FAILED: %0d errors", failed);

        $finish;
    end

    // Timeout watchdog
    initial begin
        #100000;
        $display("TIMEOUT");
        $finish;
    end

endmodule
